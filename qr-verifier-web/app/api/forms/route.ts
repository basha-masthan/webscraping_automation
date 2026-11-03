import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const page = parseInt(searchParams.get("page") || "1", 10);
    const limit = parseInt(searchParams.get("limit") || "25", 10);
    const search = searchParams.get("search") || "";
    const status = searchParams.get("status") || "all";
    const verificationStatus = searchParams.get("verificationStatus") || "all";

    const { db } = await connectToDatabase();
    const query: any = {};

    if (search.trim()) {
      const q = search.trim();
      const num = parseInt(q, 10);
      if (!isNaN(num)) {
        query.$or = [
          { qr_number: num },
          { name: { $regex: q, $options: "i" } },
          { company: { $regex: q, $options: "i" } },
          { email: { $regex: q, $options: "i" } },
        ];
      } else {
        query.$or = [
          { name: { $regex: q, $options: "i" } },
          { company: { $regex: q, $options: "i" } },
          { email: { $regex: q, $options: "i" } },
          { designation: { $regex: q, $options: "i" } },
        ];
      }
    }

    if (status !== "all") {
      query.status = status;
    }

    if (verificationStatus !== "all") {
      query.verification_status = verificationStatus;
    }

    const total = await db.collection("qr_forms").countDocuments(query);
    const forms = await db
      .collection("qr_forms")
      .find(query)
      .sort({ qr_number: 1 })
      .skip((page - 1) * limit)
      .limit(limit)
      .toArray();

    // Summary statistics
    const totalForms = await db.collection("qr_forms").countDocuments({});
    const adminVerifiedCount = await db.collection("qr_forms").countDocuments({ verification_status: "admin_verified" });
    const userVerifiedCount = await db.collection("qr_forms").countDocuments({ verification_status: "user_verified" });
    const userUpdatedCount = await db.collection("qr_forms").countDocuments({ verification_status: "user_updated" });
    const unverifiedCount = await db.collection("qr_forms").countDocuments({ verification_status: "unverified" });

    return NextResponse.json({
      success: true,
      data: forms,
      pagination: {
        page,
        limit,
        total,
        totalPages: Math.ceil(total / limit),
      },
      stats: {
        total: totalForms,
        adminVerified: adminVerifiedCount,
        userVerified: userVerifiedCount,
        userUpdated: userUpdatedCount,
        unverified: unverifiedCount,
      },
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

