import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { passkey } = await req.json();
    const expected = process.env.ADMIN_PASSKEY || "adminbasha";

    if (passkey === expected) {
      return NextResponse.json({ success: true });
    }
    return NextResponse.json({ success: false, error: "Incorrect admin passkey" }, { status: 401 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}

