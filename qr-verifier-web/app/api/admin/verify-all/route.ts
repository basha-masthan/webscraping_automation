import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function POST(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { action, qrNumbers } = await req.json();
    const { db } = await connectToDatabase();
    const now = new Date().toISOString();

    if (action === "admin_verify_all_user_verified") {
      // Verify all forms that were verified by users
      const res = await db.collection("qr_forms").updateMany(
        { verification_status: "user_verified" },
        {
          $set: {
            verification_status: "admin_verified",
            status: "admin_verified",
            admin_verified_at: now,
          },
        }
      );
      return NextResponse.json({
        success: true,
        message: `Admin verified ${res.modifiedCount} user-verified forms`,
        count: res.modifiedCount,
      });
    } else if (action === "admin_verify_all_user_updated") {
      // Verify all forms that were updated by users
      const res = await db.collection("qr_forms").updateMany(
        { verification_status: "user_updated" },
        {
          $set: {
            verification_status: "admin_verified",
            status: "admin_verified",
            admin_verified_at: now,
          },
        }
      );
      return NextResponse.json({
        success: true,
        message: `Admin verified ${res.modifiedCount} updated forms`,
        count: res.modifiedCount,
      });
    } else if (action === "admin_verify_selected" && Array.isArray(qrNumbers)) {
      const res = await db.collection("qr_forms").updateMany(
        { qr_number: { $in: qrNumbers } },
        {
          $set: {
            verification_status: "admin_verified",
            status: "admin_verified",
            admin_verified_at: now,
          },
        }
      );
      return NextResponse.json({
        success: true,
        message: `Admin verified ${res.modifiedCount} selected forms`,
        count: res.modifiedCount,
      });
    }

    return NextResponse.json({ success: false, error: "Invalid action" }, { status: 400 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

