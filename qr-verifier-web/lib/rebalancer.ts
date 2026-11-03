import { Db } from "mongodb";

export async function rebalanceAssignments(db: Db): Promise<{
  activeUsers: string[];
  totalUnverified: number;
  perUserCount: number;
}> {
  // 1. Get all active tokens
  const activeTokens = await db
    .collection("access_tokens")
    .find({ is_active: { $ne: false } })
    .sort({ created_at: 1 })
    .toArray();

  const userNames = Array.from(
    new Set(activeTokens.map((t) => (t.user_name || "").trim()).filter(Boolean))
  );

  if (userNames.length === 0) {
    return { activeUsers: [], totalUnverified: 0, perUserCount: 0 };
  }

  // 2. Fetch all unverified forms sorted by qr_number
  const unverifiedForms = await db
    .collection("qr_forms")
    .find({ verification_status: "unverified" }, { projection: { qr_number: 1 } })
    .sort({ qr_number: 1 })
    .toArray();

  const total = unverifiedForms.length;
  if (total === 0) {
    return { activeUsers: userNames, totalUnverified: 0, perUserCount: 0 };
  }

  const k = userNames.length;
  const chunkSize = Math.ceil(total / k);

  const bulkOps: any[] = [];
  for (let i = 0; i < k; i++) {
    const user = userNames[i];
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize, total);
    const slice = unverifiedForms.slice(start, end);

    if (slice.length > 0) {
      const qrNumbers = slice.map((f) => f.qr_number);
      bulkOps.push({
        updateMany: {
          filter: { qr_number: { $in: qrNumbers }, verification_status: "unverified" },
          update: { $set: { assigned_to: user } },
        },
      });
    }
  }

  if (bulkOps.length > 0) {
    await db.collection("qr_forms").bulkWrite(bulkOps);
  }

  return {
    activeUsers: userNames,
    totalUnverified: total,
    perUserCount: chunkSize,
  };
}

