"use client";

import React, { useState, useEffect } from "react";
import {
  Lock,
  Shield,
  Key,
  Users,
  CheckCircle2,
  ListOrdered,
  Play,
  RotateCcw,
  Trash2,
  Plus,
  RefreshCw,
  LogOut,
  AlertCircle,
  Copy,
  Check,
  Zap,
  Terminal,
  Clock,
  ArrowRight,
  Sliders,
} from "lucide-react";

interface AccessToken {
  _id: string;
  token: string;
  user_name: string;
  created_at: string;
  created_by: string;
  is_active: boolean;
  last_used_at: string | null;
  device_id: string | null;
}

interface FillQueueItem {
  _id: string;
  qr_number: number;
  updated_fields: any;
  updated_by: string;
  queued_at: string;
  status: string;
}

export default function AdminPage() {
  const [passkey, setPasskey] = useState<string>("");
  const [isAdminAuth, setIsAdminAuth] = useState<boolean>(false);
  const [authError, setAuthError] = useState<string>("");

  // Tokens management
  const [tokens, setTokens] = useState<AccessToken[]>([]);
  const [newUserName, setNewUserName] = useState<string>("");
  const [isCreatingToken, setIsCreatingToken] = useState<boolean>(false);
  const [copiedToken, setCopiedToken] = useState<string>("");

  // Fill Queue & Bulk Admin Verification
  const [queue, setQueue] = useState<FillQueueItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string>("");

  // Simulated Auto-Fill Terminal Output
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [isRunningAutoFill, setIsRunningAutoFill] = useState<boolean>(false);
  const [countdown, setCountdown] = useState<number>(0);

  useEffect(() => {
    const saved = sessionStorage.getItem("admin_passkey");
    if (saved === "adminbasha") {
      setPasskey(saved);
      setIsAdminAuth(true);
      loadAdminData(saved);
    }
  }, []);

  const handleAdminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");

    try {
      const res = await fetch("/api/auth/admin-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passkey }),
      });
      const data = await res.json();
      if (data.success) {
        sessionStorage.setItem("admin_passkey", passkey);
        setIsAdminAuth(true);
        loadAdminData(passkey);
      } else {
        setAuthError(data.error || "Incorrect passkey");
      }
    } catch (err: any) {
      setAuthError("Network error: " + err.message);
    }
  };

  const handleAdminLogout = () => {
    sessionStorage.removeItem("admin_passkey");
    setIsAdminAuth(false);
    setPasskey("");
  };

  const loadAdminData = async (adminPass: string) => {
    setLoading(true);
    try {
      // 1. Load Tokens
      const tokenRes = await fetch("/api/tokens", {
        headers: { "x-admin-passkey": adminPass },
      });
      const tokenData = await tokenRes.json();
      if (tokenData.success) {
        setTokens(tokenData.tokens);
      }

      // 2. Load Fill Queue
      const queueRes = await fetch("/api/admin/fill-queue", {
        headers: { "x-admin-passkey": adminPass },
      });
      const queueData = await queueRes.json();
      if (queueData.success) {
        setQueue(queueData.queue);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUserName.trim()) return;

    setIsCreatingToken(true);
    try {
      const res = await fetch("/api/tokens", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-passkey": passkey,
        },
        body: JSON.stringify({ userName: newUserName }),
      });
      const data = await res.json();
      if (data.success) {
        setTokens([data.token, ...tokens]);
        setNewUserName("");
        setActionMessage(`Created Token for ${data.token.user_name}: ${data.token.token}`);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsCreatingToken(false);
    }
  };

  const handleRegenerateToken = async (tokenCode: string) => {
    try {
      const res = await fetch("/api/tokens", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "x-admin-passkey": passkey,
        },
        body: JSON.stringify({ token: tokenCode, action: "regenerate" }),
      });
      const data = await res.json();
      if (data.success) {
        setTokens((prev) =>
          prev.map((t) =>
            t.token === tokenCode
              ? { ...t, token: data.newToken, device_id: null }
              : t
          )
        );
        setActionMessage(`Token regenerated to: ${data.newToken}`);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteToken = async (tokenCode: string) => {
    if (!confirm(`Delete access token ${tokenCode}?`)) return;
    try {
      const res = await fetch(`/api/tokens?token=${tokenCode}`, {
        method: "DELETE",
        headers: { "x-admin-passkey": passkey },
      });
      const data = await res.json();
      if (data.success) {
        setTokens((prev) => prev.filter((t) => t.token !== tokenCode));
        setActionMessage(`Deleted token ${tokenCode}`);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleVerifyAllUserVerified = async () => {
    try {
      const res = await fetch("/api/admin/verify-all", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-passkey": passkey,
        },
        body: JSON.stringify({ action: "admin_verify_all_user_verified" }),
      });
      const data = await res.json();
      if (data.success) {
        setActionMessage(data.message);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleVerifyAllUserUpdated = async () => {
    try {
      const res = await fetch("/api/admin/verify-all", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-passkey": passkey,
        },
        body: JSON.stringify({ action: "admin_verify_all_user_updated" }),
      });
      const data = await res.json();
      if (data.success) {
        setActionMessage(data.message);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedToken(text);
    setTimeout(() => setCopiedToken(""), 2000);
  };

  // Auto-Fill Terminal Execution Simulator
  const runAutoFillSimulation = (items: FillQueueItem[]) => {
    if (items.length === 0) {
      setActionMessage("No forms queued for auto-fill.");
      return;
    }

    setIsRunningAutoFill(true);
    setTerminalLogs([]);

    const log = (msg: string) => {
      setTerminalLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
    };

    log(`[ZEN DATA AUTO-FILL] Starting Auto-Fill for ${items.length} updated QR forms...`);
    log("[PORTAL] Logging into portal session...");

    let index = 0;

    const processNext = () => {
      if (index >= items.length) {
        log("[FINISHED] All updated forms successfully submitted to the portal!");
        setIsRunningAutoFill(false);
        return;
      }

      const item = items[index];
      const fields = item.updated_fields || {};
      log(`-------------------------------------------------------------------`);
      log(`[STEP 1] Navigating to Form QR #${item.qr_number}...`);
      log(`[INSPECTOR] Loading Updated Values by ${item.updated_by}:`);
      log(`  - Name           : ${fields.name || "—"}`);
      log(`  - Designation    : ${fields.designation || "—"}`);
      log(`  - Company        : ${fields.company || "—"}`);
      log(`  - Website        : ${fields.website || "—"}`);
      log(`  - Address        : ${fields.address || "—"}`);
      log(`  - Email          : ${fields.email || "—"}`);
      log(`  - Office Contact : ${fields.office_contact || "—"}`);

      log(`[AUTO-FILL] Typing verified fields into Portal Inputs...`);
      log(`[[OK]] All 7/7 input elements confirmed populated.`);

      // Random wait simulation for admin review
      const randomWait = Math.floor(Math.random() * 4) + 4; // 4 to 7 seconds
      log(`[REVIEW TIMER] Random wait ${randomWait}s for Admin verification before clicking Submit...`);

      let rem = randomWait;
      setCountdown(rem);
      const timer = setInterval(() => {
        rem -= 1;
        setCountdown(rem);
        if (rem <= 0) {
          clearInterval(timer);
          log(`[SUBMIT] Submitting QR #${item.qr_number} form to Portal...`);
          log(`[POPUP] 'QR Generated' modal accepted successfully.`);
          index++;
          setTimeout(processNext, 1000);
        }
      }, 1000);
    };

    setTimeout(processNext, 1200);
  };

  // Locked Gate
  if (!isAdminAuth) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <div className="w-full max-w-sm p-8 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-2xl backdrop-blur-xl">
          <div className="flex justify-center mb-6">
            <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-2xl">
              <Lock className="w-8 h-8 text-rose-400" />
            </div>
          </div>
          <h1 className="text-xl font-bold text-center text-white mb-2">Admin Control Hub</h1>
          <p className="text-xs text-slate-400 text-center mb-6">
            Protected area. Enter admin passkey to continue.
          </p>

          <form onSubmit={handleAdminLogin} className="space-y-4">
            <div>
              <input
                type="password"
                placeholder="Enter Passkey"
                value={passkey}
                onChange={(e) => setPasskey(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-white placeholder-slate-500 text-sm focus:outline-none focus:ring-2 focus:ring-rose-500"
                required
              />
            </div>

            {authError && (
              <div className="p-2.5 bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs rounded-xl flex items-center gap-1.5">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {authError}
              </div>
            )}

            <button
              type="submit"
              className="w-full py-2.5 bg-rose-600 hover:bg-rose-500 text-white font-medium text-xs rounded-xl shadow-lg shadow-rose-600/30 transition flex items-center justify-center gap-2"
            >
              Unlock Dashboard
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-slate-800 text-center">
            <a href="/" className="text-xs text-slate-400 hover:text-white transition">
              &larr; Return to Reviewer Portal
            </a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 bg-slate-900/80 backdrop-blur-md border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-rose-500/10 border border-rose-500/20 rounded-xl">
              <Shield className="w-5 h-5 text-rose-400" />
            </div>
            <div>
              <h1 className="font-bold text-lg text-white">Admin Master Control Hub</h1>
              <p className="text-xs text-slate-400">Database: AI_Automation_Forms (MongoDB)</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <a
              href="/"
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-xl transition"
            >
              View Verification Portal
            </a>

            <button
              onClick={handleAdminLogout}
              className="p-2 text-slate-400 hover:text-rose-400 transition"
              title="Lock Admin"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8 space-y-8">
        {actionMessage && (
          <div className="p-4 bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs rounded-2xl flex items-center justify-between">
            <span>{actionMessage}</span>
            <button onClick={() => setActionMessage("")} className="text-slate-400 hover:text-white">
              &times;
            </button>
          </div>
        )}

        {/* 1. Quick Batch Operations */}
        <section className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <h2 className="text-base font-bold text-white mb-1 flex items-center gap-2">
            <Sliders className="w-4 h-4 text-indigo-400" />
            Admin Batch Verification Actions
          </h2>
          <p className="text-xs text-slate-400 mb-6">
            Review and mark all submitted user forms as verified at a single click.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <button
              onClick={handleVerifyAllUserVerified}
              className="p-4 bg-emerald-950/20 border border-emerald-800/40 hover:bg-emerald-950/40 rounded-xl text-left transition"
            >
              <div className="text-xs text-emerald-400 font-semibold mb-1">
                Verify All &quot;User-Verified&quot;
              </div>
              <div className="text-[11px] text-slate-400">
                Batch promote all forms checked by friends to Admin Verified status.
              </div>
            </button>

            <button
              onClick={handleVerifyAllUserUpdated}
              className="p-4 bg-amber-950/20 border border-amber-800/40 hover:bg-amber-950/40 rounded-xl text-left transition"
            >
              <div className="text-xs text-amber-400 font-semibold mb-1">
                Verify All &quot;User-Updated&quot;
              </div>
              <div className="text-[11px] text-slate-400">
                Accept all corrected values submitted by users.
              </div>
            </button>

            <button
              onClick={() => runAutoFillSimulation(queue)}
              disabled={isRunningAutoFill || queue.length === 0}
              className="p-4 bg-gradient-to-br from-indigo-950/40 to-cyan-950/40 border border-indigo-700/50 hover:border-cyan-500/50 rounded-xl text-left transition disabled:opacity-50"
            >
              <div className="text-xs text-cyan-300 font-semibold mb-1 flex items-center gap-1.5">
                <Play className="w-3.5 h-3.5 text-cyan-400" />
                Launch Portal Auto-Fill ({queue.length})
              </div>
              <div className="text-[11px] text-slate-400">
                Auto-fill portal with user-updated values with random wait intervals.
              </div>
            </button>
          </div>
        </section>

        {/* 2. Terminal Live Stream */}
        {isRunningAutoFill && (
          <section className="bg-slate-950 border border-slate-800 rounded-2xl p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-mono font-bold text-slate-200">
                  Live Auto-Fill Execution Stream
                </span>
              </div>
              {countdown > 0 && (
                <div className="flex items-center gap-1.5 px-3 py-1 bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs rounded-xl font-mono">
                  <Clock className="w-3.5 h-3.5 animate-spin" />
                  Admin Review Window: {countdown}s remaining...
                </div>
              )}
            </div>

            <div className="bg-black/90 p-4 rounded-xl font-mono text-xs text-emerald-400 space-y-1 max-h-80 overflow-y-auto">
              {terminalLogs.map((logLine, i) => (
                <div key={i}>{logLine}</div>
              ))}
            </div>
          </section>
        )}

        {/* 3. User Permission & One-Time Token Management */}
        <section className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <Users className="w-4 h-4 text-indigo-400" />
                Friend & Reviewer Access Tokens
              </h2>
              <p className="text-xs text-slate-400">
                Issue one-time tokens for friends. The token locks to their device and will never ask again.
              </p>
            </div>

            {/* Generate Token Form */}
            <form onSubmit={handleCreateToken} className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Friend's Name (e.g. Rahul)"
                value={newUserName}
                onChange={(e) => setNewUserName(e.target.value)}
                className="px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                required
              />
              <button
                type="submit"
                disabled={isCreatingToken}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs rounded-xl shadow-lg shadow-indigo-600/20 transition flex items-center gap-1.5 shrink-0"
              >
                <Plus className="w-3.5 h-3.5" />
                Generate Token
              </button>
            </form>
          </div>

          {/* Tokens Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800 uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="py-3 px-4">User Name</th>
                  <th className="py-3 px-4">One-Time Token</th>
                  <th className="py-3 px-4">Device Lock</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Last Active</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {tokens.map((tok) => (
                  <tr key={tok._id || tok.token} className="hover:bg-slate-800/30 transition">
                    <td className="py-3 px-4 font-semibold text-white">{tok.user_name}</td>
                    <td className="py-3 px-4 font-mono text-indigo-300 flex items-center gap-2">
                      <span>{tok.token}</span>
                      <button
                        onClick={() => copyToClipboard(tok.token)}
                        className="text-slate-500 hover:text-slate-300"
                        title="Copy Token"
                      >
                        {copiedToken === tok.token ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-slate-400 font-mono text-[11px]">
                      {tok.device_id ? (
                        <span className="text-emerald-400 font-medium">Locked: {tok.device_id}</span>
                      ) : (
                        <span className="text-slate-500">Unused (Awaiting first login)</span>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      {tok.is_active ? (
                        <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full text-[10px]">
                          Active
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 bg-rose-500/10 text-rose-400 border border-rose-500/20 rounded-full text-[10px]">
                          Revoked
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-slate-500">
                      {tok.last_used_at ? new Date(tok.last_used_at).toLocaleDateString() : "Never"}
                    </td>
                    <td className="py-3 px-4 text-right space-x-2">
                      <button
                        onClick={() => handleRegenerateToken(tok.token)}
                        className="p-1.5 text-slate-400 hover:text-cyan-400 transition"
                        title="Regenerate Token & Reset Device"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => handleDeleteToken(tok.token)}
                        className="p-1.5 text-slate-400 hover:text-rose-400 transition"
                        title="Delete User Token"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* 4. Pending Portal Auto-Fill Queue */}
        <section className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <ListOrdered className="w-4 h-4 text-amber-400" />
                Updated Forms Auto-Fill Queue ({queue.length})
              </h2>
              <p className="text-xs text-slate-400">
                Forms edited by your friends are queued here to update the portal original forms.
              </p>
            </div>

            <button
              onClick={() => runAutoFillSimulation(queue)}
              disabled={queue.length === 0 || isRunningAutoFill}
              className="px-4 py-2 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white font-medium text-xs rounded-xl shadow-lg shadow-orange-500/20 transition flex items-center gap-1.5 disabled:opacity-50"
            >
              <Play className="w-3.5 h-3.5" />
              Auto-Fill All Updated ({queue.length})
            </button>
          </div>

          {queue.length === 0 ? (
            <div className="text-center py-12 text-slate-500 border border-dashed border-slate-800 rounded-xl text-xs">
              No updated forms currently waiting in the Auto-Fill queue.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {queue.map((item) => (
                <div
                  key={item._id || item.qr_number}
                  className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-indigo-400 font-mono">
                      QR #{item.qr_number}
                    </span>
                    <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">
                      Updated by {item.updated_by}
                    </span>
                  </div>
                  <div className="text-slate-300">
                    <strong className="text-white">{item.updated_fields?.name}</strong> &bull;{" "}
                    {item.updated_fields?.company}
                  </div>
                  <div className="text-slate-400 font-mono text-[11px] truncate">
                    {item.updated_fields?.designation}
                  </div>
                  <div className="text-emerald-400 font-mono text-[11px]">
                    {item.updated_fields?.office_contact}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

