import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI QR Form Verification Hub",
  description: "Collaborative QR Business Card Verification & Auto-Fill System",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
