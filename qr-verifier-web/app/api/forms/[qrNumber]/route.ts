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

    return NextResponse.json({ success: true, data: form });
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

    if (action === "verify_no_errors") {
      // User confirms form is 100% correct without changes
      const uName = (userName || "Reviewer").trim();
      await db.collection("qr_forms").updateOne(
        { qr_number: num },
        {
          $set: {
            verification_status: "user_verified",
            status: "verified",
            verified_by: uName,
            verified_at: now,
            updated_at: now,
          },
        }
      );
      return NextResponse.json({ success: true, message: `Marked verified by ${uName}` });
    } else if (action === "update_form") {
      // User found errors and edited fields
      const uName = (userName || "Reviewer").trim();
      if (!updatedFields || typeof updatedFields !== "object") {
        return NextResponse.json({ success: false, error: "Missing updated fields" }, { status: 400 });
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
        // Save previous version snapshot
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

      await db.collection("qr_forms").updateOne({ qr_number: num }, { $set: updatePayload });

      // Automatically push into fill_queue so Admin can Auto-Fill original portal
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

      return NextResponse.json({
        success: true,
        message: `Updated by ${uName} and queued for portal auto-fill`,
      });
    } else if (action === "admin_verify") {
      // Admin verification
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

