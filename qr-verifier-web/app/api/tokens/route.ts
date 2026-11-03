import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";
import { randomBytes } from "crypto";

export async function GET(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { db } = await connectToDatabase();
    const tokens = await db
      .collection("access_tokens")
      .find({})
      .sort({ created_at: -1 })
      .toArray();

    return NextResponse.json({ success: true, tokens });
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

    const { userName } = await req.json();
    if (!userName || !userName.trim()) {
      return NextResponse.json({ success: false, error: "User name is required" }, { status: 400 });
    }

    const tokenCode = `TOKEN-${randomBytes(6).toString("hex").toUpperCase()}`;
    const { db } = await connectToDatabase();

    const doc = {
      token: tokenCode,
      user_name: userName.trim(),
      created_at: new Date().toISOString(),
      created_by: "admin",
      is_active: true,
      last_used_at: null,
      device_id: null,
    };

    await db.collection("access_tokens").insertOne(doc);
    return NextResponse.json({ success: true, token: doc });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { token, action } = await req.json();
    const { db } = await connectToDatabase();

    if (action === "regenerate") {
      const newTokenCode = `TOKEN-${randomBytes(6).toString("hex").toUpperCase()}`;
      await db.collection("access_tokens").updateOne(
        { token },
        {
          $set: {
            token: newTokenCode,
            device_id: null, // reset device binding on regenerate
            updated_at: new Date().toISOString(),
          },
        }
      );
      return NextResponse.json({ success: true, newToken: newTokenCode });
    } else if (action === "toggle_active") {
      const existing = await db.collection("access_tokens").findOne({ token });
      if (existing) {
        await db.collection("access_tokens").updateOne(
          { token },
          { $set: { is_active: !existing.is_active } }
        );
      }
      return NextResponse.json({ success: true });
    } else if (action === "reset_device") {
      await db.collection("access_tokens").updateOne(
        { token },
        { $set: { device_id: null } }
      );
      return NextResponse.json({ success: true, message: "Device binding reset" });
    }

    return NextResponse.json({ success: false, error: "Invalid action" }, { status: 400 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const adminPass = req.headers.get("x-admin-passkey");
    if (adminPass !== (process.env.ADMIN_PASSKEY || "adminbasha")) {
      return NextResponse.json({ success: false, error: "Unauthorized" }, { status: 401 });
    }

    const { searchParams } = new URL(req.url);
    const token = searchParams.get("token");
    if (!token) {
      return NextResponse.json({ success: false, error: "Token is required" }, { status: 400 });
    }

    const { db } = await connectToDatabase();
    await db.collection("access_tokens").deleteOne({ token });
    return NextResponse.json({ success: true, message: "Token deleted successfully" });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

