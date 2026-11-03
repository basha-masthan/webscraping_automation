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
  ExternalLink,
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
  status: string;
  verification_status: "admin_verified" | "user_verified" | "user_updated" | "unverified";
  verified_by?: string;
  verified_at?: string;
  updated_by?: string;
  updated_at?: string;
  ocr_raw_text?: string;
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

  // Edit modal
  const [editingForm, setEditingForm] = useState<QRForm | null>(null);
  const [editFields, setEditFields] = useState<any>({});
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccess, setSaveSuccess] = useState<string>("");

  // Quick verify feedback
  const [verifyingId, setVerifyingId] = useState<number | null>(null);

  // 1. Device ID initialization
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
        limit: "20",
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

  const handleMarkVerifiedNoErrors = async (form: QRForm) => {
    setVerifyingId(form.qr_number);
    try {
      const res = await fetch(`/api/forms/${form.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "verify_no_errors",
          userName: userName,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setForms((prev) =>
          prev.map((f) =>
            f.qr_number === form.qr_number
              ? {
                  ...f,
                  verification_status: "user_verified",
                  verified_by: userName,
                  verified_at: new Date().toISOString(),
                }
              : f
          )
        );
      }
    } catch (err) {
      console.error(err);
    } finally {
      setVerifyingId(null);
    }
  };

  const openEditModal = (form: QRForm) => {
    setEditingForm(form);
    setEditFields({
      name: form.name,
      designation: form.designation,
      company: form.company,
      website: form.website,
      address: form.address,
      email: form.email,
      office_contact: form.office_contact,
    });
    setSaveSuccess("");
  };

  const handleSaveEdit = async () => {
    if (!editingForm) return;
    setIsSaving(true);
    try {
      const res = await fetch(`/api/forms/${editingForm.qr_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "update_form",
          userName: userName,
          updatedFields: editFields,
        }),
      });
      const data = await res.json();
      if (data.success) {
        setSaveSuccess(`Updated by ${userName}! Queued for Auto-Fill.`);
        setForms((prev) =>
          prev.map((f) =>
            f.qr_number === editingForm.qr_number
              ? {
                  ...f,
                  ...editFields,
                  verification_status: "user_updated",
                  updated_by: userName,
                  updated_at: new Date().toISOString(),
                }
              : f
          )
        );
        setTimeout(() => {
          setEditingForm(null);
        }, 1200);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsSaving(false);
    }
  };

  // Auth gate view
  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen px-4">
        <div className="w-full max-w-md p-8 bg-slate-900/80 border border-slate-800 rounded-2xl shadow-2xl backdrop-blur-xl">
          <div className="flex justify-center mb-6">
            <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-2xl">
              <Shield className="w-10 h-10 text-indigo-400" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-center text-white mb-2">
            AI QR Verification Portal
          </h1>
          <p className="text-sm text-slate-400 text-center mb-6">
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
                  className="w-full pl-11 pr-4 py-2.5 bg-slate-950 border border-slate-700 rounded-xl text-white placeholder-slate-500 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
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
              className="w-full py-3 px-4 bg-gradient-to-r from-indigo-500 to-cyan-500 hover:from-indigo-600 hover:to-cyan-600 text-white font-medium rounded-xl shadow-lg shadow-indigo-500/25 transition flex items-center justify-center gap-2 disabled:opacity-50"
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
    <div className="min-h-screen flex flex-col">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 bg-slate-900/80 backdrop-blur-md border-b border-slate-800 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-500/10 border border-indigo-500/20 rounded-xl">
              <Zap className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h1 className="font-bold text-lg text-white">AI Automation Forms Verifier</h1>
              <p className="text-xs text-slate-400">Collaborative QR Verification Hub</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 border border-slate-700/60 rounded-xl text-xs text-slate-300">
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
              title="Logout"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
        {/* Statistics Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-8">
          <div className="p-4 bg-slate-900/60 border border-slate-800 rounded-2xl">
            <div className="text-xs text-slate-400">Total Cards</div>
            <div className="text-2xl font-bold text-white mt-1">{stats.total || 0}</div>
          </div>
          <div className="p-4 bg-emerald-950/20 border border-emerald-900/30 rounded-2xl">
            <div className="text-xs text-emerald-400">Admin Verified</div>
            <div className="text-2xl font-bold text-emerald-300 mt-1">{stats.adminVerified || 0}</div>
          </div>
          <div className="p-4 bg-cyan-950/20 border border-cyan-900/30 rounded-2xl">
            <div className="text-xs text-cyan-400">User Verified</div>
            <div className="text-2xl font-bold text-cyan-300 mt-1">{stats.userVerified || 0}</div>
          </div>
          <div className="p-4 bg-amber-950/20 border border-amber-900/30 rounded-2xl">
            <div className="text-xs text-amber-400">User Updated</div>
            <div className="text-2xl font-bold text-amber-300 mt-1">{stats.userUpdated || 0}</div>
          </div>
          <div className="p-4 bg-rose-950/20 border border-rose-900/30 rounded-2xl col-span-2 sm:col-span-1">
            <div className="text-xs text-rose-400">Unverified</div>
            <div className="text-2xl font-bold text-rose-300 mt-1">{stats.unverified || 0}</div>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search by QR number, Name, Company, or Email..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                fetchForms(1, e.target.value, filterStatus);
              }}
              className="w-full pl-10 pr-4 py-2 bg-slate-900 border border-slate-800 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={filterStatus}
              onChange={(e) => {
                setFilterStatus(e.target.value);
                fetchForms(1, search, e.target.value);
              }}
              className="bg-slate-900 border border-slate-800 rounded-xl text-sm text-slate-200 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="all">All Statuses</option>
              <option value="unverified">Unverified Only</option>
              <option value="user_verified">User Verified</option>
              <option value="user_updated">User Updated (Queued for Fill)</option>
              <option value="admin_verified">Admin Verified</option>
            </select>

            <button
              onClick={() => fetchForms(page, search, filterStatus)}
              className="p-2 bg-slate-900 border border-slate-800 hover:bg-slate-800 rounded-xl text-slate-300 transition"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {/* Cards Grid */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-24 text-slate-400">
            <RefreshCw className="w-8 h-8 animate-spin text-indigo-400 mb-3" />
            <span>Loading verified forms from MongoDB...</span>
          </div>
        ) : forms.length === 0 ? (
          <div className="text-center py-20 text-slate-500 border border-dashed border-slate-800 rounded-2xl">
            No matching QR forms found.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {forms.map((form) => {
              const isAdm = form.verification_status === "admin_verified";
              const isUsrVer = form.verification_status === "user_verified";
              const isUsrUpd = form.verification_status === "user_updated";

              return (
                <div
                  key={form.qr_number}
                  className="bg-slate-900/60 border border-slate-800/80 hover:border-slate-700/80 rounded-2xl p-6 transition flex flex-col justify-between shadow-lg"
                >
                  <div>
                    {/* Header */}
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <span className="px-2.5 py-1 bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded-lg text-xs font-mono font-bold">
                          QR #{form.qr_number}
                        </span>
                        <h2 className="font-semibold text-white text-base">{form.name || "Untitled Name"}</h2>
                      </div>

                      {/* Status Tag */}
                      {isAdm ? (
                        <span className="px-2.5 py-0.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-medium rounded-full flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Admin Verified
                        </span>
                      ) : isUsrVer ? (
                        <span className="px-2.5 py-0.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs font-medium rounded-full flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Verified by {form.verified_by}
                        </span>
                      ) : isUsrUpd ? (
                        <span className="px-2.5 py-0.5 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-medium rounded-full flex items-center gap-1">
                          <Edit3 className="w-3 h-3" /> Updated by {form.updated_by}
                        </span>
                      ) : (
                        <span className="px-2.5 py-0.5 bg-slate-800 text-slate-400 text-xs font-medium rounded-full">
                          Unverified
                        </span>
                      )}
                    </div>

                    {/* Fields List */}
                    <div className="space-y-2 text-xs mb-6">
                      <div className="flex items-start gap-2 text-slate-300">
                        <Briefcase className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Designation:</span>
                        <span className="text-slate-100 font-mono">{form.designation || "—"}</span>
                      </div>

                      <div className="flex items-start gap-2 text-slate-300">
                        <Building className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Company:</span>
                        <span className="text-slate-100 font-mono font-semibold">{form.company || "—"}</span>
                      </div>

                      <div className="flex items-start gap-2 text-slate-300">
                        <Globe className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Website:</span>
                        <a
                          href={form.website.startsWith("http") ? form.website : `https://${form.website}`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-indigo-400 hover:underline font-mono truncate"
                        >
                          {form.website || "—"}
                        </a>
                      </div>

                      <div className="flex items-start gap-2 text-slate-300">
                        <MapPin className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Address:</span>
                        <span className="text-slate-100 font-mono">{form.address || "—"}</span>
                      </div>

                      <div className="flex items-start gap-2 text-slate-300">
                        <Mail className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Email:</span>
                        <span className="text-slate-100 font-mono">{form.email || "—"}</span>
                      </div>

                      <div className="flex items-start gap-2 text-slate-300">
                        <Phone className="w-3.5 h-3.5 text-slate-500 shrink-0 mt-0.5" />
                        <span className="font-medium text-slate-400 shrink-0">Office Contact:</span>
                        <span className="text-slate-100 font-mono font-semibold text-emerald-400">
                          {form.office_contact || "—"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Actions Bar */}
                  <div className="pt-4 border-t border-slate-800/80 flex items-center justify-between gap-3">
                    <button
                      onClick={() => openEditModal(form)}
                      className="flex-1 py-2 px-3 bg-slate-800 hover:bg-slate-700/80 text-slate-200 text-xs font-medium rounded-xl transition flex items-center justify-center gap-1.5"
                    >
                      <Edit3 className="w-3.5 h-3.5 text-amber-400" />
                      Update Form
                    </button>

                    <button
                      onClick={() => handleMarkVerifiedNoErrors(form)}
                      disabled={verifyingId === form.qr_number || isAdm}
                      className="flex-1 py-2 px-3 bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 text-xs font-medium rounded-xl transition flex items-center justify-center gap-1.5 disabled:opacity-50"
                    >
                      {verifyingId === form.qr_number ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                      )}
                      Verified by {userName}
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

      {/* Edit Modal */}
      {editingForm && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl p-6 shadow-2xl overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between pb-4 border-b border-slate-800 mb-6">
              <div>
                <h3 className="font-bold text-lg text-white">
                  Update Form: QR #{editingForm.qr_number}
                </h3>
                <p className="text-xs text-slate-400">
                  Will be recorded as Updated by {userName} and queued for Original Portal Auto-Fill
                </p>
              </div>
              <button
                onClick={() => setEditingForm(null)}
                className="text-slate-400 hover:text-white"
              >
                &times;
              </button>
            </div>

            {saveSuccess && (
              <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-xl text-xs flex items-center gap-2">
                <Check className="w-4 h-4" />
                {saveSuccess}
              </div>
            )}

            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-slate-400 font-medium mb-1">Full Name</label>
                <input
                  type="text"
                  value={editFields.name || ""}
                  onChange={(e) => setEditFields({ ...editFields, name: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Designation</label>
                <input
                  type="text"
                  value={editFields.designation || ""}
                  onChange={(e) => setEditFields({ ...editFields, designation: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Company</label>
                <input
                  type="text"
                  value={editFields.company || ""}
                  onChange={(e) => setEditFields({ ...editFields, company: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Website URL</label>
                <input
                  type="text"
                  value={editFields.website || ""}
                  onChange={(e) => setEditFields({ ...editFields, website: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div>
                <label className="block text-slate-400 font-medium mb-1">Address</label>
                <input
                  type="text"
                  value={editFields.address || ""}
                  onChange={(e) => setEditFields({ ...editFields, address: e.target.value })}
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 font-medium mb-1">Email</label>
                  <input
                    type="email"
                    value={editFields.email || ""}
                    onChange={(e) => setEditFields({ ...editFields, email: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 font-medium mb-1">Office Contact</label>
                  <input
                    type="text"
                    value={editFields.office_contact || ""}
                    onChange={(e) => setEditFields({ ...editFields, office_contact: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white font-mono focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {editingForm.ocr_raw_text && (
                <div className="mt-4 p-3 bg-slate-950 border border-slate-800/80 rounded-xl">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider block mb-1">
                    Raw OCR Reference:
                  </span>
                  <div className="text-[11px] font-mono text-slate-400 break-words">
                    {editingForm.ocr_raw_text}
                  </div>
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 mt-6 pt-4 border-t border-slate-800">
              <button
                onClick={() => setEditingForm(null)}
                className="px-4 py-2 bg-slate-800 text-slate-300 text-xs font-medium rounded-xl hover:bg-slate-700 transition"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={isSaving}
                className="px-5 py-2 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-xs font-semibold rounded-xl shadow-lg shadow-orange-500/20 transition flex items-center gap-1.5"
              >
                {isSaving ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Edit3 className="w-3.5 h-3.5" />}
                Submit Update by {userName}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
