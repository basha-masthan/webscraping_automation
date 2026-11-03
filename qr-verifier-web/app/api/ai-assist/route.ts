import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const { ocr_raw_text, current_form } = await req.json();

    if (!ocr_raw_text && !current_form) {
      return NextResponse.json({ success: false, error: "Missing text for AI extraction" }, { status: 400 });
    }

    const groqKey = process.env.GROQ_API_KEY;
    const openrouterKey = process.env.OPENROUTER_API_KEY;

    const prompt = `You are a high-precision OCR data extraction assistant for business card forms.
Extract exactly the following 7 fields from this text.
CRITICAL RULES:
1. "name": Full name of person. Do not include trailing commas.
2. "designation": Job title. Do not include company, email, or address.
3. "company": Company name only.
4. "website": Exact website URL as printed. Do NOT invent http:// or https:// if absent.
5. "address": VERBATIM address. NEVER invent commas or punctuation. Keep exact spacing.
6. "email": Email address.
7. "office_contact": ALL phone numbers including area codes and separators like "/" or " / ". Never drop secondary phone numbers!

Input Text:
"""
${ocr_raw_text || JSON.stringify(current_form)}
"""

Respond with STRICT JSON ONLY matching this schema:
{
  "name": "...",
  "designation": "...",
  "company": "...",
  "website": "...",
  "address": "...",
  "email": "...",
  "office_contact": "..."
}`;

    // 1. Try Groq (qwen/qwen3.8-27b)
    if (groqKey) {
      try {
        const groqRes = await fetch("https://api.groq.com/openai/v1/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${groqKey}`,
          },
          body: JSON.stringify({
            model: "qwen/qwen3.8-27b",
            messages: [{ role: "user", content: prompt }],
            temperature: 0.1,
            response_format: { type: "json_object" },
          }),
        });

        if (groqRes.ok) {
          const data = await groqRes.json();
          const content = data.choices?.[0]?.message?.content;
          if (content) {
            const parsed = JSON.parse(content);
            return NextResponse.json({ success: true, model: "groq/qwen3.8-27b", ai_data: parsed });
          }
        }
      } catch (e) {
        console.warn("Groq AI assist error, falling back to OpenRouter:", e);
      }
    }

    // 2. Fallback to OpenRouter
    if (openrouterKey) {
      try {
        const orRes = await fetch("https://openrouter.ai/api/v1/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${openrouterKey}`,
          },
          body: JSON.stringify({
            model: "nvidia/nemotron-3-ultra-550b-a55b:free",
            messages: [{ role: "user", content: prompt }],
            temperature: 0.1,
          }),
        });

        if (orRes.ok) {
          const data = await orRes.json();
          const content = data.choices?.[0]?.message?.content || "";
          const jsonMatch = content.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            return NextResponse.json({ success: true, model: "openrouter/nemotron", ai_data: parsed });
          }
        }
      } catch (e) {
        console.warn("OpenRouter AI assist error:", e);
      }
    }

    return NextResponse.json({ success: false, error: "AI extraction keys not configured in environment" }, { status: 502 });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
