import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function GET(req: NextRequest, { params }: { params: { qrNumber: string } }) {
  try {
    const num = parseInt(params.qrNumber, 10);
    if (isNaN(num)) {
      return NextResponse.json({ success: false, error: "Invalid QR number" }, { status: 400 });
    }

    const { db } = await connectToDatabase();
    const form = await db.collection("qr_forms").findOne({ qr_number: num });

    if (!form) {
      return NextResponse.json({ success: false, error: "Form not found" }, { status: 404 });
    }

    // Look up next unverified form
    const nextUnverified = await db.collection("qr_forms").findOne(
      {
        qr_number: { $gt: num },
        verification_status: "unverified",
      },
      { sort: { qr_number: 1 }, projection: { qr_number: 1 } }
    );

    return NextResponse.json({
      success: true,
      data: form,
      nextQrNumber: nextUnverified?.qr_number || null,
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest, { params }: { params: { qrNumber: string } }) {
  try {
    const num = parseInt(params.qrNumber, 10);
    if (isNaN(num)) {
      return NextResponse.json({ success: false, error: "Invalid QR number" }, { status: 400 });
    }

    const body = await req.json();
    const { action, userName, updatedFields, adminPasskey } = body;
    const { db } = await connectToDatabase();

    const existing = await db.collection("qr_forms").findOne({ qr_number: num });
    if (!existing) {
      return NextResponse.json({ success: false, error: "Form not found" }, { status: 404 });
    }

    const now = new Date().toISOString();
    const uName = (userName || "Reviewer").trim();

    // 1. Lock acquisition / heartbeat check
    if (action === "acquire_lock") {
      const active = existing.active_reviewer;
      const isLockedByOther =
        active &&
        active.name !== uName &&
        Date.now() - new Date(active.timestamp).getTime() < 45000;

      if (isLockedByOther) {
        return NextResponse.json({
          success: true,
          isLocked: true,
          lockedBy: active.name,
          message: `${active.name} is currently reviewing this form.`,
        });
      }

      await db.collection("qr_forms").updateOne(
        { qr_number: num },
        {
          $set: {
            active_reviewer: { name: uName, timestamp: now },
          },
        }
      );
      return NextResponse.json({ success: true, isLocked: false });
    }

    // 2. Release lock
    if (action === "release_lock") {
      if (existing.active_reviewer?.name === uName) {
        await db.collection("qr_forms").updateOne(
          { qr_number: num },
          { $unset: { active_reviewer: "" } }
        );
      }
      return NextResponse.json({ success: true });
    }

    // Helper: Find next unverified form for this user (or overflow pool)
    const findNextUnverified = async () => {
      // 1. Try next form assigned to this user
      if (uName) {
        const nextAssigned = await db.collection("qr_forms").findOne(
          {
            qr_number: { $gt: num },
            assigned_to: uName,
            verification_status: "unverified",
          },
          { sort: { qr_number: 1 }, projection: { qr_number: 1 } }
        );
        if (nextAssigned) return nextAssigned.qr_number;

        // Wrap around inside user's assignment
        const firstAssigned = await db.collection("qr_forms").findOne(
          {
            assigned_to: uName,
            verification_status: "unverified",
          },
          { sort: { qr_number: 1 }, projection: { qr_number: 1 } }
        );
        if (firstAssigned) return firstAssigned.qr_number;
      }

      // 2. If user completed their batch, steal work from global unverified queue
      const nextGlobal = await db.collection("qr_forms").findOne(
        {
          qr_number: { $gt: num },
          verification_status: "unverified",
        },
        { sort: { qr_number: 1 }, projection: { qr_number: 1 } }
      );
      if (nextGlobal) return nextGlobal.qr_number;

      const firstGlobal = await db.collection("qr_forms").findOne(
        {
          verification_status: "unverified",
        },
        { sort: { qr_number: 1 }, projection: { qr_number: 1 } }
      );
      return firstGlobal?.qr_number || null;
    };

    // 3. Verify No Errors Action
    if (action === "verify_no_errors") {
      const alreadyHandledByOther =
        (existing.verification_status === "user_verified" && existing.verified_by !== uName) ||
        (existing.verification_status === "user_updated" && existing.updated_by !== uName) ||
        existing.verification_status === "admin_verified";

      if (alreadyHandledByOther) {
        const who = existing.updated_by || existing.verified_by || "another user";
        const nextQr = await findNextUnverified();
        return NextResponse.json({
          success: false,
          conflict: true,
          completedBy: who,
          message: `This form was already completed by ${who}! Advancing to next form...`,
          nextQrNumber: nextQr,
        });
      }

      await db.collection("qr_forms").updateOne(
        { qr_number: num },
        {
          $set: {
            verification_status: "user_verified",
            status: "verified",
            verified_by: uName,
            verified_at: now,
            updated_at: now,
            version: (existing.version || 1) + 1,
          },
          $unset: { active_reviewer: "" },
        }
      );

      const nextQr = await findNextUnverified();

      return NextResponse.json({
        success: true,
        message: `Marked verified by ${uName}`,
        nextQrNumber: nextQr,
      });
    }

    // 4. Update Form Action
    if (action === "update_form") {
      if (!updatedFields || typeof updatedFields !== "object") {
        return NextResponse.json({ success: false, error: "Missing updated fields" }, { status: 400 });
      }

      const alreadyUpdatedByOther =
        (existing.verification_status === "user_updated" && existing.updated_by !== uName) ||
        existing.verification_status === "admin_verified";

      if (alreadyUpdatedByOther) {
        const who = existing.updated_by || "another user";
        const nextQr = await findNextUnverified();
        return NextResponse.json({
          success: false,
          conflict: true,
          completedBy: who,
          message: `Form was already updated by ${who}! Advancing to next form...`,
          nextQrNumber: nextQr,
        });
      }

      const updatePayload: any = {
        name: updatedFields.name?.trim() || existing.name,
        designation: updatedFields.designation?.trim() || existing.designation,
        company: updatedFields.company?.trim() || existing.company,
        website: updatedFields.website?.trim() || existing.website,
        address: updatedFields.address?.trim() || existing.address,
        email: updatedFields.email?.trim() || existing.email,
        office_contact: updatedFields.office_contact?.trim() || existing.office_contact,
        verification_status: "user_updated",
        updated_by: uName,
        updated_at: now,
        version: (existing.version || 1) + 1,
        previous_data: {
          name: existing.name,
          designation: existing.designation,
          company: existing.company,
          website: existing.website,
          address: existing.address,
          email: existing.email,
          office_contact: existing.office_contact,
        },
      };

      await db.collection("qr_forms").updateOne(
        { qr_number: num },
        {
          $set: updatePayload,
          $unset: { active_reviewer: "" },
        }
      );

      // Queue for Portal Auto-Fill
      await db.collection("fill_queue").updateOne(
        { qr_number: num },
        {
          $set: {
            qr_number: num,
            updated_fields: updatePayload,
            updated_by: uName,
            queued_at: now,
            status: "pending_auto_fill",
          },
        },
        { upsert: true }
      );

      const nextQr = await findNextUnverified();

      return NextResponse.json({
        success: true,
        message: `Updated by ${uName} and queued for portal auto-fill`,
        nextQrNumber: nextQr,
      });
    }

    // 5. Admin verification
    if (action === "admin_verify") {
      if (adminPasskey !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
        return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
      }

      await db.collection("qr_forms").updateOne(
        { qr_number: num },
        {
          $set: {
            verification_status: "admin_verified",
            status: "admin_verified",
            verified_by: "admin",
            verified_at: now,
            updated_at: now,
          },
        }
      );
      return NextResponse.json({ success: true, message: "Marked admin verified" });
    }

    return NextResponse.json({ success: false, error: "Invalid action" }, { status: 400 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
