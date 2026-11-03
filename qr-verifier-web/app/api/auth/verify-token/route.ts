import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function POST(req: NextRequest) {
  try {
    const { token, deviceId } = await req.json();
    if (!token) {
      return NextResponse.json({ success: false, error: "Access token is required" }, { status: 400 });
    }

    const { db } = await connectToDatabase();
    const tokenDoc = await db.collection("access_tokens").findOne({
      token: token.trim().toUpperCase(),
      is_active: true,
    });

    if (!tokenDoc) {
      return NextResponse.json({ success: false, error: "Invalid or revoked access token" }, { status: 401 });
    }

    // One-time device lock: bind token to deviceId if not bound yet
    if (deviceId && !tokenDoc.device_id) {
      await db.collection("access_tokens").updateOne(
        { _id: tokenDoc._id },
        {
          $set: {
            device_id: deviceId,
            last_used_at: new Date().toISOString(),
          },
        }
      );
    } else if (deviceId && tokenDoc.device_id && tokenDoc.device_id !== deviceId) {
      return NextResponse.json(
        { success: false, error: "This access token is already bound to another device." },
        { status: 403 }
      );
    } else {
      await db.collection("access_tokens").updateOne(
        { _id: tokenDoc._id },
        { $set: { last_used_at: new Date().toISOString() } }
      );
    }

    return NextResponse.json({
      success: true,
      userName: tokenDoc.user_name,
      token: tokenDoc.token,
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

