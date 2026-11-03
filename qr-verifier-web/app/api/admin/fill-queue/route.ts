import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function GET(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { db } = await connectToDatabase();
    const queue = await db
      .collection("fill_queue")
      .find({})
      .sort({ queued_at: -1 })
      .toArray();

    return NextResponse.json({ success: true, queue });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { action, qrNumber } = await req.json();
    const { db } = await connectToDatabase();

    if (action === "queue_for_fill") {
      // Find form data and add to fill queue
      const form = await db.collection("qr_forms").findOne({ qr_number: qrNumber });
      if (!form) {
        return NextResponse.json({ success: false, error: "Form not found" }, { status: 404 });
      }

      await db.collection("fill_queue").updateOne(
        { qr_number: qrNumber },
        {
          $set: {
            qr_number: qrNumber,
            updated_fields: form,
            updated_by: "admin",
            queued_at: new Date().toISOString(),
            status: "pending_auto_fill",
          },
        },
        { upsert: true }
      );

      return NextResponse.json({ success: true, message: `Queued QR #${qrNumber} for form-filling` });
    } else if (action === "queue_all_updated") {
      const updatedForms = await db
        .collection("qr_forms")
        .find({ verification_status: "user_updated" })
        .toArray();

      for (const f of updatedForms) {
        await db.collection("fill_queue").updateOne(
          { qr_number: f.qr_number },
          {
            $set: {
              qr_number: f.qr_number,
              updated_fields: f,
              updated_by: f.updated_by || "user",
              queued_at: new Date().toISOString(),
              status: "pending_auto_fill",
            },
          },
          { upsert: true }
        );
      }

      return NextResponse.json({
        success: true,
        message: `Queued ${updatedForms.length} updated forms for auto-filling`,
      });
    }

    return NextResponse.json({ success: false, error: "Invalid action" }, { status: 400 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

