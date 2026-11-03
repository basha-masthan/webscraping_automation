"use client";

import React, { useState, useEffect } from "react";
import {
  Shield,
  Key,
  CheckCircle2,
  Edit3,
  Search,
  Filter,
  RefreshCw,
  LogOut,
  ChevronLeft,
  ChevronRight,
  User,
  Building,
  Mail,
  Phone,
  Globe,
  MapPin,
  Briefcase,
  AlertCircle,
  Copy,
  Check,
  Zap,
  Sparkles,
  Maximize2,
  ArrowRight,
  Clock,
  Eye,
} from "lucide-react";

interface QRForm {
  _id: string;
  qr_number: number;
  qr_label: string;
  name: string;
  designation: string;
  company: string;
  website: string;
  address: string;
  email: string;
  office_contact: string;
  image_url?: string;
  image_data?: {
    name?: string;
    designation?: string;
    company?: string;
    website?: string;
    address?: string;
    email?: string;
    office_contact?: string;
  };
  ocr_raw_text?: string;
  discrepancies?: string;
  status: string;
  verification_status: "admin_verified" | "user_verified" | "user_updated" | "unverified";
  verified_by?: string;
  verified_at?: string;
  updated_by?: string;
  updated_at?: string;
  version?: number;
  active_reviewer?: {
    name: string;
    timestamp: string;
  };
}

export default function Home() {
  // Auth state
  const [authToken, setAuthToken] = useState<string>("");
  const [userName, setUserName] = useState<string>("");
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [authError, setAuthError] = useState<string>("");
  const [isVerifyingToken, setIsVerifyingToken] = useState<boolean>(false);

  // Forms state
  const [forms, setForms] = useState<QRForm[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [stats, setStats] = useState<any>({});
  const [search, setSearch] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  // Review / Edit Modal
  const [activeForm, setActiveForm] = useState<QRForm | null>(null);
  const [formData, setFormData] = useState<any>({});
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [notification, setNotification] = useState<{ type: "success" | "error" | "warning"; text: string } | null>(null);
  const [lockWarning, setLockWarning] = useState<string | null>(null);

  // AI Assist
  const [isAiLoading, setIsAiLoading] = useState<boolean>(false);
  const [aiSuggestions, setAiSuggestions] = useState<any>(null);

  // Quick verify feedback
  const [verifyingId, setVerifyingId] = useState<number | null>(null);

  // 1. Initial Device ID & Token Auth Check
  useEffect(() => {
    let devId = localStorage.getItem("qr_device_id");
    if (!devId) {
      devId = "DEV-" + Math.random().toString(36).substring(2, 12).toUpperCase();
      localStorage.setItem("qr_device_id", devId);
    }

    const savedToken = localStorage.getItem("qr_auth_token");
    const savedUser = localStorage.getItem("qr_user_name");
    if (savedToken && savedUser) {
      setAuthToken(savedToken);
      setUserName(savedUser);
      setIsAuthenticated(true);
      fetchForms(1, search, filterStatus);
    }
  }, []);

  const handleTokenLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authToken.trim()) return;

    setIsVerifyingToken(true);
    setAuthError("");

    try {
      const devId = localStorage.getItem("qr_device_id");
      const res = await fetch("/api/auth/verify-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: authToken.trim(), deviceId: devId }),
      });

      const data = await res.json();
      if (data.success) {
        localStorage.setItem("qr_auth_token", data.token);
        localStorage.setItem("qr_user_name", data.userName);
        setUserName(data.userName);
        setIsAuthenticated(true);
        fetchForms(1, search, filterStatus);
      } else {
        setAuthError(data.error || "Failed to authenticate token");
      }
    } catch (err: any) {
      setAuthError("Network error: " + err.message);
    } finally {
      setIsVerifyingToken(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("qr_auth_token");
    localStorage.removeItem("qr_user_name");
    setIsAuthenticated(false);
    setAuthToken("");
    setUserName("");
  };

  const fetchForms = async (pageNum = 1, searchQuery = "", statusQuery = "all") => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: pageNum.toString(),
        limit: "18",
        search: searchQuery,
        verificationStatus: statusQuery,
      });

      const res = await fetch(`/api/forms?${params.toString()}`);
      const data = await res.json();
      if (data.success) {
        setForms(data.data);
        setPage(data.pagination.page);
        setTotalPages(data.pagination.totalPages);
        setTotalCount(data.pagination.total);
        setStats(data.stats);
      }
    } catch (err) {
      console.error("Error fetching forms:", err);
    } finally {
      setLoading(false);
    }
  };

  // Open Form Verification & Acquire Lock
  const openVerificationModal = async (form: QRForm) => {
    setActiveForm(form);
    setFormData({
      name: form.name || "",
      designation: form.designation || "",
      company: form.company || "",
      website: form.website || "",
      address: form.address || "",
      email: form.email || "",
      office_contact: form.office_contact || "",
    });
    setNotification(null);
    setLockWarning(null);
    setAiSuggestions(null);

    // Acquire heartbeat lock
    try {
      const res = await fetch(`/api/forms/${form.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "acquire_lock", userName }),
      });
      const lockData = await res.json();
      if (lockData.isLocked) {
        setLockWarning(`⚠️ ${lockData.lockedBy} is currently reviewing this form. Changes submitted first will take precedence.`);
      }
    } catch (e) {
      console.warn("Lock acquire error:", e);
    }
  };

  const closeVerificationModal = async () => {
    if (activeForm) {
      // Release lock
      fetch(`/api/forms/${activeForm.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "release_lock", userName }),
      }).catch(() => {});
    }
    setActiveForm(null);
  };

  // Load a specific QR number into modal
  const loadSpecificForm = async (qrNum: number) => {
    try {
      const res = await fetch(`/api/forms/${qrNum}`);
      const data = await res.json();
      if (data.success && data.data) {
        openVerificationModal(data.data);
      } else {
        closeVerificationModal();
        fetchForms(page, search, filterStatus);
      }
    } catch (e) {
      closeVerificationModal();
    }
  };

  // 1. Action: Mark Verified (No Errors)
  const handleVerifyNoErrors = async () => {
    if (!activeForm) return;
    setIsSaving(true);
    setNotification(null);

    try {
      const res = await fetch(`/api/forms/${activeForm.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "verify_no_errors",
          userName: userName,
        }),
      });
      const data = await res.json();

      if (data.conflict) {
        // Concurrency conflict - other user finished first
        setNotification({
          type: "warning",
          text: data.message,
        });
        setTimeout(() => {
          if (data.nextQrNumber) {
            loadSpecificForm(data.nextQrNumber);
          } else {
            closeVerificationModal();
            fetchForms(page, search, filterStatus);
          }
        }, 1800);
      } else if (data.success) {
        setNotification({
          type: "success",
          text: `Marked as Verified by ${userName}! Moving to next form...`,
        });

        // Update list in background
        setForms((prev) =>
          prev.map((f) =>
            f.qr_number === activeForm.qr_number
              ? {
                  ...f,
                  verification_status: "user_verified",
                  status: "verified",
                  verified_by: userName,
                  verified_at: new Date().toISOString(),
                }
              : f
          )
        );

        // Advance to next form immediately
        setTimeout(() => {
          if (data.nextQrNumber) {
            loadSpecificForm(data.nextQrNumber);
          } else {
            setNotification({ type: "success", text: "All forms verified! Great work." });
            setTimeout(() => {
              closeVerificationModal();
              fetchForms(page, search, filterStatus);
            }, 1200);
          }
        }, 800);
      } else {
        setNotification({ type: "error", text: data.error || "Failed to verify" });
      }
    } catch (err: any) {
      setNotification({ type: "error", text: err.message });
    } finally {
      setIsSaving(false);
    }
  };

  // 2. Action: Save Updates
  const handleSaveUpdate = async () => {
    if (!activeForm) return;
    setIsSaving(true);
    setNotification(null);

    try {
      const res = await fetch(`/api/forms/${activeForm.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "update_form",
          userName: userName,
          updatedFields: formData,
        }),
      });
      const data = await res.json();

      if (data.conflict) {
        setNotification({
          type: "warning",
          text: data.message,
        });
        setTimeout(() => {
          if (data.nextQrNumber) {
            loadSpecificForm(data.nextQrNumber);
          } else {
            closeVerificationModal();
            fetchForms(page, search, filterStatus);
          }
        }, 1800);
      } else if (data.success) {
        setNotification({
          type: "success",
          text: `Saved & Updated by ${userName}! Queued for Auto-Fill. Moving to next form...`,
        });

        setForms((prev) =>
          prev.map((f) =>
            f.qr_number === activeForm.qr_number
              ? {
                  ...f,
                  ...formData,
                  verification_status: "user_updated",
                  updated_by: userName,
                  updated_at: new Date().toISOString(),
                }
              : f
          )
        );

        setTimeout(() => {
          if (data.nextQrNumber) {
            loadSpecificForm(data.nextQrNumber);
          } else {
            closeVerificationModal();
            fetchForms(page, search, filterStatus);
          }
        }, 800);
      } else {
        setNotification({ type: "error", text: data.error || "Failed to update" });
      }
    } catch (err: any) {
      setNotification({ type: "error", text: err.message });
    } finally {
      setIsSaving(false);
    }
  };

  // 3. AI Assistant Trigger
  const handleAskAi = async () => {
    if (!activeForm) return;
    setIsAiLoading(true);
    try {
      const res = await fetch("/api/ai-assist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ocr_raw_text: activeForm.ocr_raw_text,
          current_form: formData,
        }),
      });
      const data = await res.json();
      if (data.success && data.ai_data) {
        setAiSuggestions(data.ai_data);
      } else {
        alert("AI models could not re-extract: " + (data.error || "Unknown"));
      }
    } catch (err: any) {
      alert("AI error: " + err.message);
    } finally {
      setIsAiLoading(false);
    }
  };

  // Helper to copy a field from extracted/image_data into the filled form
  const copyExtractedField = (field: string, val: string | undefined) => {
    if (!val) return;
    setFormData((prev: any) => ({ ...prev, [field]: val }));
  };

  // Auth gate view
  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4 bg-slate-950">
        <div className="w-full max-w-md p-8 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-2xl backdrop-blur-xl">
          <div className="flex justify-center mb-6">
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl">
              <Shield className="w-10 h-10 text-indigo-400" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-center text-white mb-2">
            AI QR Verification Portal
          </h1>
          <p className="text-xs text-slate-400 text-center mb-6">
            Enter your one-time Verification Access Token provided by the admin.
          </p>

          <form onSubmit={handleTokenLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 uppercase tracking-wider mb-2">
                Verification Token
              </label>
              <div className="relative">
                <Key className="absolute left-3.5 top-3 w-5 h-5 text-slate-500" />
                <input
                  type="text"
                  placeholder="e.g. TOKEN-82E131DC02E4"
                  value={authToken}
                  onChange={(e) => setAuthToken(e.target.value.toUpperCase())}
                  className="w-full pl-11 pr-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-white placeholder-slate-500 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent text-sm"
                  required
                />
              </div>
            </div>

            {authError && (
              <div className="flex items-center gap-2 p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl text-xs text-rose-400">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{authError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={isVerifyingToken}
              className="w-full py-3 px-4 bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-600 hover:to-cyan-600 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/25 transition flex items-center justify-center gap-2 disabled:opacity-50 text-sm"
            >
              {isVerifyingToken ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Verifying Device...
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  Access Verification Queue
                </>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-slate-800 flex justify-between text-xs text-slate-500">
            <span>Admin?</span>
            <a href="/admin" className="text-indigo-400 hover:text-indigo-300 transition">
              Open Admin Control Hub &rarr;
            </a>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 bg-slate-900/90 backdrop-blur-md border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-xl">
              <Zap className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h1 className="font-bold text-lg text-white">AI Automation Forms Verifier</h1>
              <p className="text-xs text-slate-400">Verifying Portal-Filled Data against Image Cards</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-800/80 border border-slate-700/80 rounded-xl text-xs text-slate-300">
              <User className="w-3.5 h-3.5 text-emerald-400" />
              <span>Reviewer:</span>
              <strong className="text-emerald-300 font-semibold">{userName}</strong>
            </div>

            <a
              href="/admin"
              className="px-3 py-1.5 bg-indigo-600/20 border border-indigo-500/30 hover:bg-indigo-600/30 text-indigo-300 text-xs font-medium rounded-xl transition"
            >
              Admin Hub
            </a>

            <button
              onClick={handleLogout}
              className="p-2 text-slate-400 hover:text-rose-400 transition"
              title="Logout / Switch Device"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto w-full px-6 py-8 flex-1">
        {/* Stats Row */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-8">
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-2xl">
            <span className="text-xs text-slate-400 font-medium">Total Forms</span>
            <div className="text-2xl font-bold text-white mt-1">{stats.total || totalCount}</div>
          </div>
          <div className="p-4 bg-slate-900/60 border border-amber-500/20 rounded-2xl">
            <span className="text-xs text-amber-400 font-medium">Pending Review</span>
            <div className="text-2xl font-bold text-amber-300 mt-1">{stats.unverified || 0}</div>
          </div>
          <div className="p-4 bg-slate-900/60 border border-emerald-500/20 rounded-2xl">
            <span className="text-xs text-emerald-400 font-medium">User Verified</span>
            <div className="text-2xl font-bold text-emerald-300 mt-1">{stats.userVerified || 0}</div>
          </div>
          <div className="p-4 bg-slate-900/60 border border-cyan-500/20 rounded-2xl">
            <span className="text-xs text-cyan-400 font-medium">User Updated</span>
            <div className="text-2xl font-bold text-cyan-300 mt-1">{stats.userUpdated || 0}</div>
          </div>
          <div className="p-4 bg-slate-900/60 border border-indigo-500/20 rounded-2xl">
            <span className="text-xs text-indigo-400 font-medium">Admin Verified</span>
            <div className="text-2xl font-bold text-indigo-300 mt-1">{stats.adminVerified || 0}</div>
          </div>
        </div>

        {/* Search & Filter Bar */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search by QR number (e.g. 860), Name, Company, Email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchForms(1, search, filterStatus)}
              className="w-full pl-10 pr-4 py-2 bg-slate-900/80 border border-slate-800 rounded-xl text-white placeholder-slate-500 text-xs focus:ring-2 focus:ring-indigo-500 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-slate-900/80 border border-slate-800 rounded-xl p-1 text-xs">
              <button
                onClick={() => {
                  setFilterStatus("all");
                  fetchForms(1, search, "all");
                }}
                className={`px-3 py-1.5 rounded-lg transition ${
                  filterStatus === "all" ? "bg-indigo-600 text-white font-medium" : "text-slate-400 hover:text-white"
                }`}
              >
                All
              </button>
              <button
                onClick={() => {
                  setFilterStatus("unverified");
                  fetchForms(1, search, "unverified");
                }}
                className={`px-3 py-1.5 rounded-lg transition ${
                  filterStatus === "unverified" ? "bg-amber-600 text-white font-medium" : "text-slate-400 hover:text-white"
                }`}
              >
                Pending
              </button>
              <button
                onClick={() => {
                  setFilterStatus("user_verified");
                  fetchForms(1, search, "user_verified");
                }}
                className={`px-3 py-1.5 rounded-lg transition ${
                  filterStatus === "user_verified" ? "bg-emerald-600 text-white font-medium" : "text-slate-400 hover:text-white"
                }`}
              >
                Verified
              </button>
              <button
                onClick={() => {
                  setFilterStatus("user_updated");
                  fetchForms(1, search, "user_updated");
                }}
                className={`px-3 py-1.5 rounded-lg transition ${
                  filterStatus === "user_updated" ? "bg-cyan-600 text-white font-medium" : "text-slate-400 hover:text-white"
                }`}
              >
                Updated
              </button>
            </div>

            <button
              onClick={() => fetchForms(page, search, filterStatus)}
              className="p-2.5 bg-slate-900 border border-slate-800 rounded-xl text-slate-300 hover:text-white hover:bg-slate-800 transition"
              title="Refresh Queue"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {/* Forms Card Grid */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 text-slate-400">
            <RefreshCw className="w-8 h-8 animate-spin mb-3 text-indigo-400" />
            <span className="text-sm">Loading verification records from database...</span>
          </div>
        ) : forms.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 border border-dashed border-slate-800 rounded-2xl text-slate-400">
            <AlertCircle className="w-10 h-10 mb-3 text-slate-600" />
            <p className="text-sm font-medium">No forms found matching your filter</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {forms.map((form) => {
              const isUnverified = form.verification_status === "unverified";
              const isUserVerified = form.verification_status === "user_verified";
              const isUserUpdated = form.verification_status === "user_updated";
              const isAdminVerified = form.verification_status === "admin_verified";

              return (
                <div
                  key={form._id || form.qr_number}
                  className="bg-slate-900/70 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-5 shadow-lg flex flex-col justify-between transition group"
                >
                  <div>
                    {/* Header */}
                    <div className="flex items-center justify-between mb-3 pb-3 border-b border-slate-800/80">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono font-bold px-2.5 py-1 bg-slate-800 border border-slate-700/60 rounded-lg text-indigo-300">
                          QR #{form.qr_number}
                        </span>
                        {form.image_url && (
                          <span className="text-[10px] px-2 py-0.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-md flex items-center gap-1">
                            <Eye className="w-3 h-3" /> Image Attached
                          </span>
                        )}
                      </div>

                      {/* Status Badges */}
                      {isAdminVerified ? (
                        <span className="text-[11px] font-medium px-2.5 py-1 bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-lg flex items-center gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5" /> Admin Verified
                        </span>
                      ) : isUserUpdated ? (
                        <span className="text-[11px] font-medium px-2.5 py-1 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded-lg flex items-center gap-1">
                          <Edit3 className="w-3.5 h-3.5" /> Updated by {form.updated_by}
                        </span>
                      ) : isUserVerified ? (
                        <span className="text-[11px] font-medium px-2.5 py-1 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-lg flex items-center gap-1">
                          <Check className="w-3.5 h-3.5" /> Verified by {form.verified_by}
                        </span>
                      ) : (
                        <span className="text-[11px] font-medium px-2.5 py-1 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-lg">
                          Pending Review
                        </span>
                      )}
                    </div>

                    {/* Filled Form Data Snippet */}
                    <div className="space-y-1.5 text-xs mb-4">
                      <div className="font-semibold text-white text-sm line-clamp-1">
                        {form.name || "<No Name>"}
                      </div>
                      <div className="text-slate-400 line-clamp-1">{form.designation}</div>
                      <div className="text-slate-300 font-medium flex items-center gap-1.5 line-clamp-1">
                        <Building className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                        {form.company}
                      </div>
                      <div className="text-slate-400 text-[11px] flex items-center gap-1.5 line-clamp-1">
                        <Mail className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                        {form.email}
                      </div>
                      <div className="text-slate-400 text-[11px] flex items-center gap-1.5 line-clamp-1 font-mono">
                        <Phone className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                        {form.office_contact}
                      </div>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="pt-3 border-t border-slate-800/80 flex items-center gap-2">
                    <button
                      onClick={() => openVerificationModal(form)}
                      className="flex-1 py-2 px-3 bg-gradient-to-r from-indigo-500/20 to-cyan-500/20 hover:from-indigo-500/30 hover:to-cyan-500/30 border border-indigo-500/30 text-indigo-300 hover:text-white rounded-xl text-xs font-semibold transition flex items-center justify-center gap-1.5"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      Verify Form & Image
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-8 py-4 border-t border-slate-800">
            <span className="text-xs text-slate-400">
              Showing page {page} of {totalPages} ({totalCount} total)
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => fetchForms(page - 1, search, filterStatus)}
                className="p-2 bg-slate-900 border border-slate-800 rounded-xl text-slate-300 hover:bg-slate-800 transition disabled:opacity-40"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => fetchForms(page + 1, search, filterStatus)}
                className="p-2 bg-slate-900 border border-slate-800 rounded-xl text-slate-300 hover:bg-slate-800 transition disabled:opacity-40"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </main>

      {/* ======================================================= */}
      {/* FULL VERIFICATION MODAL (Image Top -> Filled Middle -> Extracted Bottom) */}
      {/* ======================================================= */}
      {activeForm && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-2 sm:p-4 overflow-y-auto">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl p-5 sm:p-7 shadow-2xl my-auto max-h-[96vh] flex flex-col overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-4 border-b border-slate-800 shrink-0">
              <div className="flex items-center gap-3">
                <span className="text-sm font-mono font-bold px-3 py-1 bg-indigo-500/20 border border-indigo-500/30 text-indigo-300 rounded-xl">
                  QR #{activeForm.qr_number}
                </span>
                <div>
                  <h3 className="font-bold text-base sm:text-lg text-white">
                    Verify Form & Business Card
                  </h3>
                  <p className="text-xs text-slate-400">
                    Review filled form against original image card. You can edit errors directly below.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => loadSpecificForm(activeForm.qr_number - 1)}
                  disabled={activeForm.qr_number <= 1}
                  className="p-2 bg-slate-800/80 hover:bg-slate-700 text-slate-300 rounded-xl transition disabled:opacity-30"
                  title="Previous QR"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={() => loadSpecificForm(activeForm.qr_number + 1)}
                  className="p-2 bg-slate-800/80 hover:bg-slate-700 text-slate-300 rounded-xl transition"
                  title="Next QR"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <button
                  onClick={closeVerificationModal}
                  className="p-2 text-slate-400 hover:text-white text-lg ml-2"
                >
                  &times;
                </button>
              </div>
            </div>

            {/* Notification / Concurrency Banner */}
            {lockWarning && (
              <div className="mt-3 p-3 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-xl text-xs flex items-center gap-2 shrink-0">
                <Clock className="w-4 h-4 shrink-0 text-amber-400" />
                <span>{lockWarning}</span>
              </div>
            )}

            {notification && (
              <div
                className={`mt-3 p-3 rounded-xl text-xs flex items-center gap-2 shrink-0 ${
                  notification.type === "success"
                    ? "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300"
                    : notification.type === "warning"
                    ? "bg-amber-500/10 border border-amber-500/30 text-amber-300"
                    : "bg-rose-500/10 border border-rose-500/30 text-rose-300"
                }`}
              >
                {notification.type === "success" ? (
                  <Check className="w-4 h-4 shrink-0" />
                ) : (
                  <AlertCircle className="w-4 h-4 shrink-0" />
                )}
                <span>{notification.text}</span>
              </div>
            )}

            {/* Scrollable Modal Content */}
            <div className="overflow-y-auto pr-1 py-4 space-y-6 flex-1 text-xs">
              {/* 1. TOP SECTION: Original Business Card Image */}
              <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 flex flex-col items-center">
                <div className="w-full flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                    <Eye className="w-3.5 h-3.5 text-indigo-400" />
                    Original Business Card Image
                  </span>
                  {activeForm.image_url && (
                    <a
                      href={activeForm.image_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 transition"
                    >
                      <Maximize2 className="w-3 h-3" /> Open Full Res
                    </a>
                  )}
                </div>

                {activeForm.image_url ? (
                  <div className="w-full h-56 sm:h-72 bg-black/60 rounded-xl border border-slate-800/80 flex items-center justify-center overflow-hidden p-2">
                    <img
                      src={activeForm.image_url}
                      alt={`QRCode - ${activeForm.qr_number} card`}
                      className="max-h-full max-w-full object-contain rounded-lg shadow-2xl"
                    />
                  </div>
                ) : (
                  <div className="w-full h-32 bg-slate-900/50 rounded-xl border border-dashed border-slate-800 flex flex-col items-center justify-center text-slate-500">
                    <AlertCircle className="w-6 h-6 mb-1 text-slate-600" />
                    <span>No image preview URL recorded for this card</span>
                  </div>
                )}
              </div>

              {/* 2. MIDDLE SECTION: Original Form Data (Submitted into Portal) */}
              <div className="bg-slate-950/90 border border-indigo-500/20 rounded-xl p-4 shadow-xl">
                <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <Edit3 className="w-4 h-4 text-cyan-400" />
                    <span className="font-bold text-sm text-white">
                      Original Form Data (Submitted into Portal)
                    </span>
                  </div>
                  <span className="text-[11px] text-cyan-400/90 bg-cyan-500/10 border border-cyan-500/20 px-2 py-0.5 rounded-md">
                    Editable by Reviewer
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Full Name
                    </label>
                    <input
                      type="text"
                      value={formData.name || ""}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Designation
                    </label>
                    <input
                      type="text"
                      value={formData.designation || ""}
                      onChange={(e) => setFormData({ ...formData, designation: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Company Name
                    </label>
                    <input
                      type="text"
                      value={formData.company || ""}
                      onChange={(e) => setFormData({ ...formData, company: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Website URL
                    </label>
                    <input
                      type="text"
                      value={formData.website || ""}
                      onChange={(e) => setFormData({ ...formData, website: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div className="sm:col-span-2">
                    <label className="block text-slate-400 font-medium mb-1">
                      Address (Verbatim, no invented commas)
                    </label>
                    <input
                      type="text"
                      value={formData.address || ""}
                      onChange={(e) => setFormData({ ...formData, address: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={formData.email || ""}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-slate-400 font-medium mb-1">
                      Office Contact (All Phone Numbers)
                    </label>
                    <input
                      type="text"
                      value={formData.office_contact || ""}
                      onChange={(e) => setFormData({ ...formData, office_contact: e.target.value })}
                      className="w-full px-3 py-2 bg-slate-900 border border-slate-700/80 rounded-xl text-white font-mono text-xs focus:ring-2 focus:ring-cyan-500 focus:outline-none"
                    />
                  </div>
                </div>
              </div>

              {/* 3. BOTTOM SECTION: Extracted Data from Image (AI & OCR Reference) */}
              <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-amber-400" />
                    <span className="font-bold text-sm text-slate-200">
                      Extracted Data from Image (AI & OCR Reference)
                    </span>
                  </div>

                  <button
                    onClick={handleAskAi}
                    disabled={isAiLoading}
                    className="px-2.5 py-1 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 text-amber-300 rounded-lg text-xs font-medium transition flex items-center gap-1.5"
                  >
                    <Zap className={`w-3.5 h-3.5 ${isAiLoading ? "animate-spin" : ""}`} />
                    {isAiLoading ? "Re-Extracting with AI..." : "Re-Check with Groq / AI"}
                  </button>
                </div>

                {/* AI Suggestions if generated */}
                {aiSuggestions && (
                  <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-amber-300">
                        ⚡ AI Assistant Fresh Suggestion:
                      </span>
                      <button
                        onClick={() => setFormData({ ...formData, ...aiSuggestions })}
                        className="px-2 py-0.5 bg-amber-500 text-slate-950 font-bold rounded text-[11px] hover:bg-amber-400 transition"
                      >
                        Apply All AI Values
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono text-amber-200">
                      <div>Name: {aiSuggestions.name}</div>
                      <div>Designation: {aiSuggestions.designation}</div>
                      <div>Company: {aiSuggestions.company}</div>
                      <div>Website: {aiSuggestions.website}</div>
                      <div className="sm:col-span-2">Address: {aiSuggestions.address}</div>
                      <div>Email: {aiSuggestions.email}</div>
                      <div>Contact: {aiSuggestions.office_contact}</div>
                    </div>
                  </div>
                )}

                {/* Comparison items with 1-click copy */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-[11px]">
                  {activeForm.image_data && (
                    <>
                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Name:{" "}
                          <strong className="text-white">{activeForm.image_data.name || "—"}</strong>
                        </span>
                        {activeForm.image_data.name && (
                          <button
                            onClick={() => copyExtractedField("name", activeForm.image_data?.name)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Designation:{" "}
                          <strong className="text-white">{activeForm.image_data.designation || "—"}</strong>
                        </span>
                        {activeForm.image_data.designation && (
                          <button
                            onClick={() => copyExtractedField("designation", activeForm.image_data?.designation)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Company:{" "}
                          <strong className="text-white">{activeForm.image_data.company || "—"}</strong>
                        </span>
                        {activeForm.image_data.company && (
                          <button
                            onClick={() => copyExtractedField("company", activeForm.image_data?.company)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Website:{" "}
                          <strong className="text-white">{activeForm.image_data.website || "—"}</strong>
                        </span>
                        {activeForm.image_data.website && (
                          <button
                            onClick={() => copyExtractedField("website", activeForm.image_data?.website)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="sm:col-span-2 p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Address:{" "}
                          <strong className="text-white">{activeForm.image_data.address || "—"}</strong>
                        </span>
                        {activeForm.image_data.address && (
                          <button
                            onClick={() => copyExtractedField("address", activeForm.image_data?.address)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Email:{" "}
                          <strong className="text-white">{activeForm.image_data.email || "—"}</strong>
                        </span>
                        {activeForm.image_data.email && (
                          <button
                            onClick={() => copyExtractedField("email", activeForm.image_data?.email)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="p-2 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-between">
                        <span className="text-slate-400">
                          Extracted Contact:{" "}
                          <strong className="text-white">{activeForm.image_data.office_contact || "—"}</strong>
                        </span>
                        {activeForm.image_data.office_contact && (
                          <button
                            onClick={() => copyExtractedField("office_contact", activeForm.image_data?.office_contact)}
                            className="p-1 text-slate-400 hover:text-cyan-400"
                            title="Copy to form"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>

                {/* Raw OCR text reference */}
                {activeForm.ocr_raw_text && (
                  <div className="mt-3 p-2.5 bg-slate-900/60 border border-slate-800/80 rounded-lg">
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
                      Raw Star-Delimited OCR Text:
                    </span>
                    <div className="text-[11px] font-mono text-slate-400 break-words">
                      {activeForm.ocr_raw_text}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Action Footer */}
            <div className="pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 shrink-0">
              <div className="flex items-center gap-2">
                <button
                  onClick={closeVerificationModal}
                  className="px-4 py-2 bg-slate-800 text-slate-300 text-xs font-medium rounded-xl hover:bg-slate-700 transition"
                >
                  Close
                </button>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleSaveUpdate}
                  disabled={isSaving}
                  className="px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white text-xs font-semibold rounded-xl shadow-lg shadow-cyan-500/20 transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  {isSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Edit3 className="w-3.5 h-3.5" />}
                  Save & Update Form &rarr; Next
                </button>

                <button
                  onClick={handleVerifyNoErrors}
                  disabled={isSaving}
                  className="px-5 py-2 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white text-xs font-bold rounded-xl shadow-lg shadow-emerald-500/25 transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  {isSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                  Verify (No Errors) &rarr; Next
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
