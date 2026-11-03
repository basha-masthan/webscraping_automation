import { NextRequest, NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";
import { rebalanceAssignments } from "@/lib/rebalancer";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const page = parseInt(searchParams.get("page") || "1", 10);
    const limit = parseInt(searchParams.get("limit") || "18", 10);
    const search = searchParams.get("search") || "";
    const filter = searchParams.get("filter") || "all"; // "all" | "pending" | "verified" | "updated"
    const userName = (searchParams.get("userName") || "").trim();

    const { db } = await connectToDatabase();

    // Check if initial assignment is needed (if unassigned unverified forms exist)
    const hasUnassigned = await db.collection("qr_forms").findOne({
      verification_status: "unverified",
      assigned_to: { $exists: false },
    });
    if (hasUnassigned) {
      await rebalanceAssignments(db);
    }

    // Work-stealing check for this user's batch
    let userAssignedPending = 0;
    if (userName) {
      userAssignedPending = await db.collection("qr_forms").countDocuments({
        assigned_to: userName,
        verification_status: "unverified",
      });
    }

    const totalUnverifiedGlobal = await db.collection("qr_forms").countDocuments({
      verification_status: "unverified",
    });

    const isWorkStealingMode = userName && userAssignedPending === 0 && totalUnverifiedGlobal > 0;

    const query: any = {};

    // Search filter
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

    // Role & Filter scoping
    if (filter === "pending") {
      query.verification_status = "unverified";
      if (userName && !isWorkStealingMode) {
        query.assigned_to = userName;
      }
    } else if (filter === "verified") {
      if (userName) {
        query.verified_by = userName;
      } else {
        query.verification_status = { $in: ["user_verified", "admin_verified"] };
      }
    } else if (filter === "updated") {
      if (userName) {
        query.updated_by = userName;
      } else {
        query.verification_status = "user_updated";
      }
    } else {
      // "all"
      if (userName && !isWorkStealingMode) {
        query.$or = [
          { assigned_to: userName },
          { verified_by: userName },
          { updated_by: userName },
        ];
      }
    }

    const total = await db.collection("qr_forms").countDocuments(query);
    const forms = await db
      .collection("qr_forms")
      .find(query)
      .sort({ qr_number: 1 })
      .skip((page - 1) * limit)
      .limit(limit)
      .toArray();

    // Summary statistics for dashboard badges
    const totalForms = await db.collection("qr_forms").countDocuments({});
    const myVerifiedCount = userName
      ? await db.collection("qr_forms").countDocuments({ verified_by: userName })
      : await db.collection("qr_forms").countDocuments({ verification_status: "user_verified" });

    const myUpdatedCount = userName
      ? await db.collection("qr_forms").countDocuments({ updated_by: userName })
      : await db.collection("qr_forms").countDocuments({ verification_status: "user_updated" });

    const adminVerifiedCount = await db
      .collection("qr_forms")
      .countDocuments({ verification_status: "admin_verified" });

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
        pending: userAssignedPending,
        globalUnverified: totalUnverifiedGlobal,
        myVerified: myVerifiedCount,
        myUpdated: myUpdatedCount,
        adminVerified: adminVerifiedCount,
        isWorkStealing: isWorkStealingMode,
      },
    });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
