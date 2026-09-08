export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8001';
const BASE = BASE_URL;

async function request(url, options = {}) {
  const token = localStorage.getItem('access_token');
  const authHeaders = token ? { 'Authorization': `Bearer ${token}` } : {};

  const timeoutMs = options.timeout || 60000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  let res;
  try {
    res = await fetch(`${BASE}${url}`, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...authHeaders,
        ...options.headers,
      },
    });
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') {
      throw new Error('Request timed out. Please try again.');
    }
    throw e;
  }
  clearTimeout(timeoutId);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Request failed' }));
    
    // Auto-logout on 401 Unauthorized
    if (res.status === 401 && token) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    }
    
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  // Screening
  uploadJD: (file, title) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('title', title);
    return request('/api/screening/upload-jd', { method: 'POST', body: fd });
  },
  uploadCVs: (files) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    return request('/api/screening/upload-cvs', { method: 'POST', body: fd });
  },
  runScreening: (jobId, candidateIds) => {
    const fd = new FormData();
    fd.append('job_id', jobId);
    fd.append('candidate_ids', candidateIds.join(','));
    return request('/api/screening/run', { method: 'POST', body: fd });
  },
  getJobs: () => request('/api/screening/jobs'),
  deleteJob: (id) => request(`/api/screening/jobs/${id}`, { method: 'DELETE' }),
  getCandidates: () => request('/api/screening/candidates'),
  getResults: (jobId) => request(`/api/screening/results/${jobId}`),
  purgeFailedCandidates: () => request('/api/screening/candidates/purge-failed', { method: 'POST' }),
  deleteCandidate: (id) => request(`/api/screening/candidates/${id}`, { method: 'DELETE' }),
  updateCandidateStatus: (id, status) => request(`/api/screening/candidate/${id}/status?status=${status}`, { method: 'POST' }),
  getCandidateRubric: (id) => request(`/api/screening/candidate/${id}/rubric`, { method: 'POST' }),

  // Dashboard
  getStats: () => request('/api/dashboard/stats'),
  getActivity: () => request('/api/dashboard/activity'),
  getVelocity: () => request('/api/dashboard/velocity'),
  getRecruitmentDashboard: () => request('/api/dashboard/recruitment'),
  getDeliveryDashboard: () => request(`/api/dashboard/delivery?t=${Date.now()}`),
  addTAActivityLog: (data) => request('/api/dashboard/activity', { method: 'POST', body: JSON.stringify(data) }),
  addSpendRequest: (data) => request('/api/dashboard/spend', { method: 'POST', body: JSON.stringify(data) }),
  approveSpendRequest: (id) => request(`/api/dashboard/spend/${id}/approve`, { method: 'POST' }),
  updateCandidateVerdict: (id, data) => request(`/api/dashboard/candidate/${id}/verdict`, { method: 'POST', body: JSON.stringify(data) }),
  updateInterviewVerdict: (id, data) => request(`/api/dashboard/interview/${id}/verdict`, { method: 'POST', body: JSON.stringify(data) }),

  // Interviews
  getInterviews: () => request('/api/interviews/'),
  createInterview: (data) => request('/api/interviews/', { method: 'POST', body: JSON.stringify(data) }),
  updateInterview: (id, data) => request(`/api/interviews/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteInterview: (id) => request(`/api/interviews/${id}`, { method: 'DELETE' }),
  suggestSlots: (candidateId) => request(`/api/interviews/suggest?candidate_id=${candidateId}`, { method: 'POST' }),
  bulkSchedule: (data) => request('/api/interviews/bulk-schedule', { method: 'POST', body: JSON.stringify(data) }),
  interviewAction: (id, action, rejectionReason) => request(`/api/interviews/${id}/action?action=${action}${rejectionReason ? `&rejection_reason=${encodeURIComponent(rejectionReason)}` : ''}`, { method: 'POST' }),
  generateEmail: (candidateId, emailType, details) => request('/api/interviews/generate-email', { method: 'POST', body: JSON.stringify({ candidate_id: candidateId, email_type: emailType, details }) }),
  sendEmail: (toEmail, subject, body) => request('/api/interviews/send-email', { method: 'POST', body: JSON.stringify({ to_email: toEmail, subject, body }) }),
  candidateAction: (id, action, rejectionReason) => request(`/api/interviews/candidate/${id}/action?action=${action}${rejectionReason ? `&rejection_reason=${encodeURIComponent(rejectionReason)}` : ''}`, { method: 'POST' }),
  scanGithub: (id, url) => request(`/api/interviews/candidate/${id}/github-scan${url ? `?url=${encodeURIComponent(url)}` : ''}`, { method: 'POST' }),
  scanLinkedin: (id, url) => request(`/api/interviews/candidate/${id}/linkedin-scan${url ? `?url=${encodeURIComponent(url)}` : ''}`, { method: 'POST' }),
  getCandidateDetails: (id) => request(`/api/screening/candidate/${id}`),
  searchCommunications: (query) => request(`/api/screening/communications/search?query=${encodeURIComponent(query)}`),
  getCandidateNotes: (id) => request(`/api/screening/candidate/${id}/notes`),
  getCandidateTimeline: (id) => request(`/api/screening/candidate/${id}/timeline`),
  addCandidateNote: (id, content) => request(`/api/screening/candidate/${id}/notes`, { method: 'POST', body: JSON.stringify({ content }) }),
  associateCandidate: (candidateId, jobId) => request('/api/screening/associate', { method: 'POST', body: JSON.stringify({ candidate_id: candidateId, job_id: jobId }) }),

  // Onboarding
  getOnboarding: () => request('/api/onboarding/'),
  addToOnboarding: (candidateId) => request(`/api/onboarding/?candidate_id=${candidateId}`, { method: 'POST' }),
  toggleTask: (taskId) => request(`/api/onboarding/task/${taskId}`, { method: 'PUT' }),
  getOnboardingStats: () => request('/api/onboarding/stats'),
  runOnboardingBot: () => request('/api/onboarding/bot/run', { method: 'POST' }),
  completeOnboarding: (candidateId) => request(`/api/onboarding/${candidateId}/complete`, { method: 'POST' }),

  // Settings
  getSMTPSettings: () => request('/api/settings/smtp'),
  updateSMTPSettings: (data) => request('/api/settings/smtp', { method: 'PUT', body: JSON.stringify(data) }),
  testSMTPSettings: (data) => request('/api/settings/smtp/test', { method: 'POST', body: JSON.stringify(data) }),
  
  getOutlookSettings: () => request('/api/settings/outlook'),
  updateOutlookSettings: (data) => request('/api/settings/outlook', { method: 'PUT', body: JSON.stringify(data) }),
  testOutlookSettings: (data) => request('/api/settings/outlook/test', { method: 'POST', body: JSON.stringify(data) }),

  getActiveEmailProvider: () => request('/api/settings/email-provider'),
  setActiveEmailProvider: (provider) => request('/api/settings/email-provider', { method: 'PUT', body: JSON.stringify({ provider }) }),

  getGCalSettings: () => request('/api/settings/gcal'),
  updateGCalSettings: (data) => request('/api/settings/gcal', { method: 'PUT', body: JSON.stringify(data) }),
  testGCalConnection: () => request('/api/settings/gcal/test', { method: 'POST' }),
  syncInterviewToGCal: (id) => request(`/api/interviews/${id}/gcal-sync`, { method: 'POST' }),

  // Assessment
  inviteCandidateToAssessment: (candidateId, jobId) => request(`/api/assessment/invite/${candidateId}?job_id=${jobId}`, { method: 'POST' }),
  getAssessmentInfo: (token) => request(`/api/assessment/info/${token}`),
  submitAssessment: (token, data) => request(`/api/assessment/submit/${token}`, { method: 'POST', body: JSON.stringify(data) }),

  // AI Sourcing
  sourceCandidates: (jobId, location) => request('/api/screening/source', { method: 'POST', body: JSON.stringify({ job_id: jobId, location }) }),
  importSourcedCandidate: (data) => request('/api/screening/import-sourced', { method: 'POST', body: JSON.stringify(data) }),

  // Webcam Upload
  uploadAssessmentRecording: (token, blob) => {
    const fd = new FormData();
    fd.append('file', blob, 'recording.webm');
    return request(`/api/assessment/upload-recording/${token}`, { method: 'POST', body: fd });
  },
  // --- CANDIDATE PORTAL ---
  signupCandidate: async (data) => {
    return request('/api/auth/signup/candidate', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  getPublishedJobs: async () => {
    return request('/api/candidate_portal/jobs');
  },

  applyForJob: async (jobId, file) => {
    const formData = new FormData();
    formData.append('resume', file);
    return request(`/api/candidate_portal/jobs/${jobId}/apply`, {
      method: 'POST',
      body: formData
    });
  },

  getMyApplications: async () => {
    return request('/api/candidate_portal/applications');
  },
  
  updateJob: async (jobId, data) => {
    return request(`/api/screening/jobs/${jobId}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  },
  createJob: async (data) => {
    return request('/api/screening/jobs', {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  // ----- Hiring Agent -----
  startAgentRun: (payload) => request('/api/agent/run', {
    method: 'POST',
    body: JSON.stringify(payload)
  }),
  listAgentRuns: (limit = 20) => request(`/api/agent/runs?limit=${limit}`),
  getAgentRun: (runId) => request(`/api/agent/runs/${runId}`),
  agentStreamUrl: (runId) => `${BASE_URL}/api/agent/runs/${runId}/stream`,

  // ----- Investigator -----
  startInvestigation: (candidateId) => request('/api/investigator/run', {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId })
  }),
  listInvestigations: (limit = 20) => request(`/api/investigator/runs?limit=${limit}`),
  getInvestigation: (runId) => request(`/api/investigator/runs/${runId}`),
  latestInvestigationFor: (candidateId) => request(`/api/investigator/candidate/${candidateId}`),
  investigatorStreamUrl: (runId) => `${BASE_URL}/api/investigator/runs/${runId}/stream`,
};
