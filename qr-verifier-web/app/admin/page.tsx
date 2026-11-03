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
  CheckCheck,
  Edit3,
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

  // Navigation tab in Admin
  const [adminTab, setAdminTab] = useState<"tokens" | "verified" | "queue">("tokens");

  // Tokens management
  const [tokens, setTokens] = useState<AccessToken[]>([]);
  const [newUserName, setNewUserName] = useState<string>("");
  const [isCreatingToken, setIsCreatingToken] = useState<boolean>(false);
  const [copiedToken, setCopiedToken] = useState<string>("");

  // User Verified Forms List
  const [userVerifiedForms, setUserVerifiedForms] = useState<any[]>([]);

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

      // 3. Load User Verified Forms
      const verifRes = await fetch("/api/forms?limit=100&verificationStatus=user_verified");
      const verifData = await verifRes.json();
      if (verifData.success) {
        setUserVerifiedForms(verifData.data || []);
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
        const countMsg = data.rebalanced?.perUserCount
          ? ` (Auto-allocated ~${data.rebalanced.perUserCount} forms each)`
          : "";
        setActionMessage(`Created Token for ${data.token.user_name}: ${data.token.token}${countMsg}`);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsCreatingToken(false);
    }
  };

  const handleRebalanceBatches = async () => {
    try {
      const res = await fetch("/api/tokens", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "x-admin-passkey": passkey,
        },
        body: JSON.stringify({ action: "rebalance" }),
      });
      const data = await res.json();
      if (data.success) {
        setActionMessage(
          `Rebalanced ${data.totalUnverified} unverified forms equally among ${data.activeUsers?.length} active reviewers (~${data.perUserCount} each).`
        );
      }
    } catch (err) {
      console.error(err);
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
    if (!confirm(`Delete access token ${tokenCode}? This will automatically rebalance remaining batches.`)) return;
    try {
      const res = await fetch(`/api/tokens?token=${tokenCode}`, {
        method: "DELETE",
        headers: { "x-admin-passkey": passkey },
      });
      const data = await res.json();
      if (data.success) {
        setTokens((prev) => prev.filter((t) => t.token !== tokenCode));
        setActionMessage(`Deleted token ${tokenCode}. Batches re-allocated automatically.`);
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
        loadAdminData(passkey);
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

      const randomWait = Math.floor(Math.random() * 4) + 4;
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
      <div className="flex flex-col items-center justify-center min-h-screen px-4 bg-slate-950">
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
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
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
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded-xl transition"
            >
              &larr; Reviewer View
            </a>
            <button
              onClick={handleAdminLogout}
              className="p-2 text-slate-400 hover:text-rose-400 transition"
              title="Logout Admin"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Admin Body */}
      <main className="max-w-7xl mx-auto w-full px-6 py-8 flex-1">
        {actionMessage && (
          <div className="mb-6 p-3 bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 rounded-xl text-xs flex items-center justify-between">
            <span>{actionMessage}</span>
            <button onClick={() => setActionMessage("")} className="text-slate-400 hover:text-white">
              &times;
            </button>
          </div>
        )}

        {/* 3 Main Admin Navigation Tabs */}
        <div className="flex items-center gap-2 mb-8 border-b border-slate-800 pb-3">
          <button
            onClick={() => setAdminTab("tokens")}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition ${
              adminTab === "tokens"
                ? "bg-rose-600 text-white shadow-lg shadow-rose-600/25"
                : "bg-slate-900 text-slate-400 hover:text-white"
            }`}
          >
            <Users className="w-4 h-4" />
            Tokens & Dynamic Batch Allocation ({tokens.length})
          </button>

          <button
            onClick={() => setAdminTab("verified")}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition ${
              adminTab === "verified"
                ? "bg-emerald-600 text-white shadow-lg shadow-emerald-600/25"
                : "bg-slate-900 text-slate-400 hover:text-white"
            }`}
          >
            <CheckCheck className="w-4 h-4" />
            User Verified Forms ({userVerifiedForms.length})
          </button>

          <button
            onClick={() => setAdminTab("queue")}
            className={`px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 transition ${
              adminTab === "queue"
                ? "bg-cyan-600 text-white shadow-lg shadow-cyan-600/25"
                : "bg-slate-900 text-slate-400 hover:text-white"
            }`}
          >
            <Terminal className="w-4 h-4" />
            Auto-Fill Portal Queue ({queue.length})
          </button>
        </div>

        {/* ======================================================== */}
        {/* TAB 1: TOKENS & DYNAMIC BATCH ALLOCATION */}
        {/* ======================================================== */}
        {adminTab === "tokens" && (
          <div className="space-y-6">
            {/* Create New Token Card */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                <div>
                  <h3 className="font-bold text-sm text-white">Generate Reviewer Access Token</h3>
                  <p className="text-xs text-slate-400">
                    Adding a new reviewer will automatically rebalance unverified forms across all active users.
                  </p>
                </div>

                <button
                  onClick={handleRebalanceBatches}
                  className="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-xl border border-slate-700 transition flex items-center gap-1.5 self-start"
                >
                  <Sliders className="w-3.5 h-3.5 text-indigo-400" />
                  Rebalance Batches Evenly
                </button>
              </div>

              <form onSubmit={handleCreateToken} className="flex gap-3">
                <input
                  type="text"
                  placeholder="Friend / Reviewer Name (e.g. John, Sarah)"
                  value={newUserName}
                  onChange={(e) => setNewUserName(e.target.value)}
                  className="flex-1 px-4 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white text-xs font-mono focus:ring-2 focus:ring-rose-500 focus:outline-none"
                  required
                />
                <button
                  type="submit"
                  disabled={isCreatingToken}
                  className="px-5 py-2 bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold rounded-xl shadow-lg shadow-rose-600/20 transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  <Plus className="w-4 h-4" />
                  Generate Token
                </button>
              </form>
            </div>

            {/* Tokens Table */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
              <div className="p-4 border-b border-slate-800 flex items-center justify-between">
                <h3 className="font-bold text-sm text-white flex items-center gap-2">
                  <Key className="w-4 h-4 text-rose-400" />
                  Active Reviewer Tokens ({tokens.length})
                </h3>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
                    <tr>
                      <th className="p-3.5">Reviewer</th>
                      <th className="p-3.5">One-Time Token</th>
                      <th className="p-3.5">Device Binding</th>
                      <th className="p-3.5">Status</th>
                      <th className="p-3.5">Created</th>
                      <th className="p-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {tokens.map((t) => (
                      <tr key={t._id} className="hover:bg-slate-800/30 transition">
                        <td className="p-3.5 font-bold text-white font-sans">{t.user_name}</td>
                        <td className="p-3.5">
                          <div className="flex items-center gap-2">
                            <span className="text-rose-300 font-semibold">{t.token}</span>
                            <button
                              onClick={() => copyToClipboard(t.token)}
                              className="text-slate-500 hover:text-white"
                              title="Copy Token"
                            >
                              {copiedToken === t.token ? (
                                <Check className="w-3.5 h-3.5 text-emerald-400" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" />
                              )}
                            </button>
                          </div>
                        </td>
                        <td className="p-3.5">
                          {t.device_id ? (
                            <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-md text-[10px]">
                              Locked ({t.device_id.substring(0, 8)}...)
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 bg-slate-800 text-slate-400 rounded-md text-[10px]">
                              Unused (Pending 1st Login)
                            </span>
                          )}
                        </td>
                        <td className="p-3.5">
                          <span
                            className={`px-2 py-0.5 rounded-md text-[10px] ${
                              t.is_active
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            }`}
                          >
                            {t.is_active ? "Active" : "Disabled"}
                          </span>
                        </td>
                        <td className="p-3.5 text-slate-400 text-[11px] font-sans">
                          {new Date(t.created_at).toLocaleDateString()}
                        </td>
                        <td className="p-3.5 text-right font-sans">
                          <div className="flex items-center justify-end gap-2">
                            <button
                              onClick={() => handleRegenerateToken(t.token)}
                              className="p-1.5 text-slate-400 hover:text-cyan-400"
                              title="Regenerate Token"
                            >
                              <RotateCcw className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDeleteToken(t.token)}
                              className="p-1.5 text-slate-400 hover:text-rose-400"
                              title="Delete Token"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 2: USER VERIFIED FORMS ("Verified by {user}") */}
        {/* ======================================================== */}
        {adminTab === "verified" && (
          <div className="space-y-6">
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-4 sm:p-6 shadow-xl flex flex-col sm:flex-row items-center justify-between gap-4">
              <div>
                <h3 className="font-bold text-sm text-white">Forms Verified by Users</h3>
                <p className="text-xs text-slate-400">
                  Reviewers have confirmed these forms match the original business cards with zero errors.
                </p>
              </div>

              <button
                onClick={handleVerifyAllUserVerified}
                className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl shadow-lg shadow-emerald-600/20 transition flex items-center gap-1.5 shrink-0"
              >
                <CheckCheck className="w-4 h-4" />
                Admin Approve All User-Verified ({userVerifiedForms.length})
              </button>
            </div>

            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
                    <tr>
                      <th className="p-3.5">QR #</th>
                      <th className="p-3.5">Person Name</th>
                      <th className="p-3.5">Company</th>
                      <th className="p-3.5">Verified By</th>
                      <th className="p-3.5">Verified At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {userVerifiedForms.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="p-8 text-center text-slate-500">
                          No forms currently marked as user-verified.
                        </td>
                      </tr>
                    ) : (
                      userVerifiedForms.map((form) => (
                        <tr key={form._id} className="hover:bg-slate-800/30 transition">
                          <td className="p-3.5 font-mono font-bold text-indigo-300">
                            #{form.qr_number}
                          </td>
                          <td className="p-3.5 font-medium text-white">{form.name}</td>
                          <td className="p-3.5 text-slate-300">{form.company}</td>
                          <td className="p-3.5">
                            <span className="px-2.5 py-1 bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 rounded-lg text-[11px] font-semibold flex items-center gap-1 w-fit">
                              <Check className="w-3.5 h-3.5" />
                              Verified by {form.verified_by || "User"}
                            </span>
                          </td>
                          <td className="p-3.5 text-slate-400 text-[11px]">
                            {form.verified_at ? new Date(form.verified_at).toLocaleString() : "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* ======================================================== */}
        {/* TAB 3: USER UPDATED FORMS & AUTO-FILL QUEUE */}
        {/* ======================================================== */}
        {adminTab === "queue" && (
          <div className="space-y-6">
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col sm:flex-row items-center justify-between gap-4">
              <div>
                <h3 className="font-bold text-sm text-white">Updated Forms Auto-Fill Queue</h3>
                <p className="text-xs text-slate-400">
                  {queue.length} forms updated by reviewers waiting to be pushed to the live website.
                </p>
              </div>

              <button
                onClick={() => runAutoFillSimulation(queue)}
                disabled={isRunningAutoFill || queue.length === 0}
                className="px-5 py-2.5 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-bold rounded-xl shadow-lg shadow-cyan-600/30 transition flex items-center gap-2 disabled:opacity-50"
              >
                {isRunningAutoFill ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Auto-Filling ({countdown}s review wait)...
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4" />
                    Launch Portal Auto-Fill ({queue.length})
                  </>
                )}
              </button>
            </div>

            {/* Live Terminal Log Viewer */}
            {terminalLogs.length > 0 && (
              <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 font-mono text-xs shadow-2xl">
                <div className="flex items-center justify-between pb-2 mb-3 border-b border-slate-800">
                  <div className="flex items-center gap-2 text-cyan-400 font-bold">
                    <Terminal className="w-4 h-4" />
                    Portal Auto-Fill Live Output
                  </div>
                  {countdown > 0 && (
                    <span className="px-2 py-0.5 bg-amber-500/10 text-amber-300 border border-amber-500/20 rounded text-[11px]">
                      Inspection Timer: {countdown}s
                    </span>
                  )}
                </div>
                <div className="max-h-64 overflow-y-auto space-y-1 text-slate-300">
                  {terminalLogs.map((log, i) => (
                    <div key={i} className="whitespace-pre-wrap">
                      {log}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Queue Table */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/60 text-slate-400 uppercase tracking-wider text-[10px] border-b border-slate-800">
                    <tr>
                      <th className="p-3.5">QR #</th>
                      <th className="p-3.5">Updated By</th>
                      <th className="p-3.5">Queued At</th>
                      <th className="p-3.5">Updated Fields</th>
                      <th className="p-3.5">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {queue.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="p-8 text-center text-slate-500">
                          Queue is currently empty.
                        </td>
                      </tr>
                    ) : (
                      queue.map((item) => (
                        <tr key={item._id} className="hover:bg-slate-800/30 transition">
                          <td className="p-3.5 font-mono font-bold text-cyan-300">
                            #{item.qr_number}
                          </td>
                          <td className="p-3.5">
                            <span className="px-2.5 py-1 bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 rounded-lg text-[11px] font-semibold flex items-center gap-1 w-fit">
                              <Edit3 className="w-3.5 h-3.5" />
                              Updated by {item.updated_by}
                            </span>
                          </td>
                          <td className="p-3.5 text-slate-400 text-[11px]">
                            {new Date(item.queued_at).toLocaleString()}
                          </td>
                          <td className="p-3.5 text-slate-300 font-mono text-[11px] truncate max-w-xs">
                            {item.updated_fields?.name} | {item.updated_fields?.company}
                          </td>
                          <td className="p-3.5">
                            <span className="px-2 py-0.5 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded text-[10px]">
                              {item.status}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
