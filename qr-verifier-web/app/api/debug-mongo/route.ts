import { NextRequest, NextResponse } from "next/server";
import * as net from "net";
import * as tls from "tls";
import * as dns from "dns/promises";

export async function GET(req: NextRequest) {
  const debugInfo: any = {
    timestamp: new Date().toISOString(),
    nodeVersion: process.version,
    envKeys: {
      hasMongodbUri: !!process.env.MONGODB_URI,
      mongodbUriLength: (process.env.MONGODB_URI || "").length,
      hasMongodbDb: !!process.env.MONGODB_DB,
      dbName: process.env.MONGODB_DB || "default",
    },
  };

  // 1. Get Vercel's outbound public IP
  try {
    const ipRes = await fetch("https://api.ipify.org?format=json");
    const ipData = await ipRes.json();
    debugInfo.vercelOutboundIp = ipData.ip;
  } catch (e: any) {
    debugInfo.vercelOutboundIpError = e.message;
  }

  // 2. DNS resolution of Atlas shard
  const targetHost = "ac-eu5fin0-shard-00-00.ymalimp.mongodb.net";
  try {
    const addresses = await dns.resolve4(targetHost);
    debugInfo.dnsResolution = { host: targetHost, addresses };
  } catch (e: any) {
    debugInfo.dnsResolution = { host: targetHost, error: e.message };
  }

  // 3. Raw TCP connection test to Port 27017
  const tcpResult: any = await new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(4000);
    socket.connect(27017, targetHost, () => {
      socket.destroy();
      resolve({ success: true, message: "TCP port 27017 connected successfully!" });
    });
    socket.on("error", (err) => resolve({ success: false, error: err.message }));
    socket.on("timeout", () => {
      socket.destroy();
      resolve({ success: false, error: "TCP connection timeout (port 27017 blocked or filtered)" });
    });
  });
  debugInfo.tcpPort27017 = tcpResult;

  // 4. Raw TLS handshake test to Port 27017
  const tlsResult: any = await new Promise((resolve) => {
    const tlsSocket = tls.connect(
      {
        host: targetHost,
        port: 27017,
        servername: targetHost,
        timeout: 4000,
        rejectUnauthorized: true,
      },
      () => {
        const cert = tlsSocket.getPeerCertificate();
        const protocol = tlsSocket.getProtocol();
        const cipher = tlsSocket.getCipher();
        tlsSocket.destroy();
        resolve({
          success: true,
          protocol,
          cipher,
          subject: cert.subject,
        });
      }
    );
    tlsSocket.on("error", (err) => resolve({ success: false, error: err.message }));
    tlsSocket.on("timeout", () => {
      tlsSocket.destroy();
      resolve({ success: false, error: "TLS handshake timeout" });
    });
  });
  debugInfo.tlsHandshake = tlsResult;

  return NextResponse.json(debugInfo);
}

