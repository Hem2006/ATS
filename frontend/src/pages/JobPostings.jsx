import React, { useState, useEffect } from 'react';
import { api, BASE_URL } from '../api/client';

export default function JobPostings() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Edit / Create Job State
  const [editingJob, setEditingJob] = useState(null); // null = not open, {} = new job, {id: ...} = existing job
  const [editForm, setEditForm] = useState({
    title: '', description: '', salary_range: '', location: '', work_mode: 'On-site', experience_level: '', is_published: false
  });
  const [saveLoading, setSaveLoading] = useState(false);
  
  // View Candidates State
  const [viewingCandidatesJob, setViewingCandidatesJob] = useState(null);
  const [jobCandidates, setJobCandidates] = useState([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);

  const [toast, setToast] = useState({ show: false, message: '', type: 'success' });

  useEffect(() => {
    fetchJobs();
  }, []);

  async function fetchJobs() {
    setLoading(true);
    try {
      const data = await api.getJobs();
      setJobs(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  const showToast = (message, type = 'success') => {
    setToast({ show: true, message, type });
    setTimeout(() => {
      setToast({ show: false, message: '', type: 'success' });
    }, 4000);
  };

  const handleCreateNewJob = () => {
    setEditingJob({});
    setEditForm({
      title: '', description: '', salary_range: '', location: '', work_mode: 'On-site', experience_level: '', is_published: false
    });
  };

  const handleEditClick = (job) => {
    setEditingJob(job);
    setEditForm({
      title: job.title || '',
      description: job.description || '',
      salary_range: job.salary_range || '',
      location: job.location || '',
      work_mode: job.work_mode || 'On-site',
      experience_level: job.experience_level || '',
      is_published: !!job.is_published
    });
  };
  
  const handleViewCandidates = async (job) => {
    setViewingCandidatesJob(job);
    setCandidatesLoading(true);
    try {
      const data = await api.getResults(job.id);
      setJobCandidates(data);
    } catch (e) {
      showToast("Failed to fetch candidates: " + e.message, "error");
    } finally {
      setCandidatesLoading(false);
    }
  };

  const handleSaveJob = async (e) => {
    e.preventDefault();
    setSaveLoading(true);
    try {
      if (editingJob.id) {
        await api.updateJob(editingJob.id, editForm);
        showToast("Job updated successfully! ✨");
      } else {
        await api.createJob(editForm);
        showToast("Job created successfully! 🎉");
      }
      setEditingJob(null);
      fetchJobs();
    } catch (e) {
      showToast("Failed to save job: " + e.message, "error");
    } finally {
      setSaveLoading(false);
    }
  };

  const togglePublish = async (job) => {
    try {
      await api.updateJob(job.id, { is_published: !job.is_published });
      fetchJobs();
      showToast(job.is_published ? "Job unpublished" : "Job published! 🚀");
    } catch (e) {
      showToast("Failed to toggle publish status: " + e.message, "error");
    }
  };

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
      <div className="spinner"></div>
    </div>
  );

  return (
    <div style={{ padding: '2rem', maxWidth: '1400px', margin: '0 auto', position: 'relative' }}>
      
      {/* Custom Toast Notification */}
      {toast.show && (
        <div style={{
          position: 'fixed', top: '2rem', left: '50%', transform: 'translateX(-50%)', zIndex: 9999,
          background: toast.type === 'success' ? '#10b981' : '#ef4444', color: '#fff',
          padding: '1rem 2rem', borderRadius: '50px', fontWeight: 600, boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
          display: 'flex', alignItems: 'center', gap: '0.75rem', animation: 'slideDown 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards'
        }}>
          <span>{toast.type === 'success' ? '✅' : '❌'}</span>
          {toast.message}
        </div>
      )}

      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2.5rem' }}>
        <div>
          <h1 className="page-title" style={{ fontSize: '2.5rem', background: 'linear-gradient(135deg, var(--blue), var(--purple))', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', fontWeight: 800 }}>Job Postings</h1>
          <p className="page-desc" style={{ fontSize: '1.1rem', color: 'var(--t2)', marginTop: '0.5rem' }}>Manage and publish job listings to the Candidate Portal.</p>
        </div>
        <button onClick={handleCreateNewJob} style={{ 
          background: 'var(--blue)', color: 'white', border: 'none', padding: '0.85rem 1.5rem', 
          borderRadius: '12px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem',
          cursor: 'pointer', boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)', transition: 'all 0.2s',
          fontSize: '1rem'
        }} className="hover-lift">
          <span style={{ fontSize: '1.2rem' }}>+</span> Create New Job
        </button>
      </div>

      <div style={{ background: 'var(--card)', borderRadius: '20px', border: '1px solid var(--border)', overflow: 'hidden', boxShadow: '0 4px 20px rgba(0,0,0,0.03)' }}>
        {jobs.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '5rem', color: 'var(--t3)' }}>
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>📭</div>
            <h3 style={{ fontSize: '1.5rem', color: 'var(--t1)', marginBottom: '0.5rem' }}>No jobs posted yet</h3>
            <p>Click "Create New Job" to add your first posting.</p>
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ background: 'var(--bg)', borderBottom: '2px solid var(--border)' }}>
                <th style={{ padding: '1.5rem', color: 'var(--t2)', fontWeight: 600 }}>Job Role</th>
                <th style={{ padding: '1.5rem', color: 'var(--t2)', fontWeight: 600 }}>Location</th>
                <th style={{ padding: '1.5rem', color: 'var(--t2)', fontWeight: 600 }}>Status</th>
                <th style={{ padding: '1.5rem', color: 'var(--t2)', fontWeight: 600, textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job, idx) => (
                <tr key={job.id} style={{ 
                  borderBottom: idx === jobs.length - 1 ? 'none' : '1px solid var(--border)',
                  transition: 'background 0.2s', ':hover': { background: 'var(--bg)' }
                }}>
                  <td style={{ padding: '1.5rem' }}>
                    <div style={{ fontWeight: 700, color: 'var(--t1)', fontSize: '1.1rem', marginBottom: '0.25rem' }}>{job.title}</div>
                    <div style={{ color: 'var(--t3)', fontSize: '0.85rem' }}>{job.experience_level || 'Experience Not Set'}</div>
                  </td>
                  <td style={{ padding: '1.5rem' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                      <span style={{ fontSize: '0.9rem', color: 'var(--t2)' }}>{job.location || 'Remote'}</span>
                      <span style={{ fontSize: '0.8rem', background: 'var(--bg)', padding: '0.2rem 0.6rem', borderRadius: '6px', border: '1px solid var(--border)', display: 'inline-block', width: 'fit-content', color: 'var(--t2)' }}>
                        {job.work_mode || 'Hybrid'}
                      </span>
                    </div>
                  </td>
                  <td style={{ padding: '1.5rem' }}>
                    <span style={{ 
                      background: job.is_published ? 'rgba(16, 185, 129, 0.1)' : 'rgba(107, 114, 128, 0.1)', 
                      color: job.is_published ? '#10b981' : '#6b7280', 
                      padding: '0.4rem 0.8rem', borderRadius: '50px', fontWeight: 600, fontSize: '0.85rem',
                      display: 'inline-flex', alignItems: 'center', gap: '0.3rem'
                    }}>
                      <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: job.is_published ? '#10b981' : '#6b7280' }}></div>
                      {job.is_published ? 'Published' : 'Draft'}
                    </span>
                  </td>
                  <td style={{ padding: '1.5rem', textAlign: 'right' }}>
                    <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                      <button onClick={() => handleViewCandidates(job)} style={{ 
                        background: 'none', border: '1px solid var(--blue)', padding: '0.5rem 1rem', 
                        borderRadius: '8px', fontWeight: 600, color: 'var(--blue)', cursor: 'pointer', transition: 'all 0.2s',
                        fontSize: '0.9rem'
                      }} className="hover-border-blue">
                        Check Resumes
                      </button>
                      <button onClick={() => handleEditClick(job)} style={{ 
                        background: 'none', border: '1px solid var(--border)', padding: '0.5rem 1rem', 
                        borderRadius: '8px', fontWeight: 600, color: 'var(--t2)', cursor: 'pointer', transition: 'all 0.2s',
                        fontSize: '0.9rem'
                      }} className="hover-border">
                        Edit
                      </button>
                      <button onClick={() => togglePublish(job)} style={{ 
                        background: job.is_published ? 'var(--bg)' : 'var(--blue-bg)', 
                        border: job.is_published ? '1px solid var(--border)' : '1px solid transparent',
                        color: job.is_published ? 'var(--t2)' : 'var(--blue)', 
                        padding: '0.5rem 1rem', borderRadius: '8px', fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
                        fontSize: '0.9rem'
                      }}>
                        {job.is_published ? 'Unpublish' : 'Publish'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* View Candidates Modal */}
      {viewingCandidatesJob && (
        <div style={{ 
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, 
          background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(5px)', 
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 
        }} onClick={() => setViewingCandidatesJob(null)}>
          <div style={{ 
            background: 'var(--card)', maxWidth: '800px', width: '95%', maxHeight: '90vh', overflowY: 'auto',
            padding: '2.5rem', borderRadius: '24px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
            border: '1px solid var(--border)', position: 'relative',
            animation: 'fadeInUp 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards'
          }} onClick={e => e.stopPropagation()}>
            <button style={{ 
              position: 'absolute', top: '1.5rem', right: '1.5rem', background: 'var(--bg)', 
              border: 'none', width: '32px', height: '32px', borderRadius: '50%', 
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', color: 'var(--t2)', fontSize: '1.2rem', transition: 'all 0.2s'
            }} onClick={() => setViewingCandidatesJob(null)}>×</button>
            
            <h2 style={{ fontSize: '1.75rem', marginBottom: '0.5rem', fontWeight: 800, color: 'var(--t1)' }}>
              Candidates for {viewingCandidatesJob.title}
            </h2>
            <p style={{ color: 'var(--t2)', marginBottom: '2rem' }}>Review the resumes submitted by candidates for this position.</p>

            {candidatesLoading ? (
               <div style={{ padding: '3rem', textAlign: 'center' }}>
                 <div className="spinner" style={{ margin: '0 auto' }}></div>
               </div>
            ) : jobCandidates.length === 0 ? (
               <div style={{ textAlign: 'center', padding: '3rem', background: 'var(--bg)', borderRadius: '12px', border: '1px dashed var(--border)' }}>
                 <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>📭</div>
                 <h3 style={{ fontSize: '1.2rem', color: 'var(--t1)' }}>No applicants yet</h3>
                 <p style={{ color: 'var(--t2)', marginTop: '0.5rem' }}>Once candidates apply, their resumes will appear here.</p>
               </div>
            ) : (
               <div style={{ display: 'grid', gap: '1rem' }}>
                 {jobCandidates.map(c => (
                   <div key={c.id} style={{ 
                     display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
                     padding: '1.5rem', background: 'var(--bg)', borderRadius: '12px', border: '1px solid var(--border)'
                   }}>
                     <div>
                       <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--t1)', marginBottom: '0.25rem' }}>{c.candidate_name}</div>
                       <div style={{ fontSize: '0.9rem', color: 'var(--t2)' }}>{c.candidate_email}</div>
                       <div style={{ fontSize: '0.85rem', color: 'var(--t3)', marginTop: '0.5rem' }}>
                         Applied on {new Date(c.created_at).toLocaleDateString()}
                       </div>
                     </div>
                     <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                       {c.resume_filename ? (
                         <a 
                           href={`${BASE_URL}/uploads/${c.resume_filename}`}
                           target="_blank" 
                           rel="noreferrer"
                           style={{ 
                             background: 'var(--blue)', color: 'white', padding: '0.75rem 1.5rem', 
                             borderRadius: '8px', textDecoration: 'none', fontWeight: 600, fontSize: '0.9rem',
                             boxShadow: '0 4px 10px rgba(59, 130, 246, 0.3)', transition: 'transform 0.2s',
                             display: 'inline-block'
                           }}
                           className="hover-lift"
                         >
                           View Resume PDF
                         </a>
                       ) : (
                         <span style={{ color: 'var(--t3)', fontSize: '0.9rem', fontStyle: 'italic' }}>No Resume Uploaded</span>
                       )}
                     </div>
                   </div>
                 ))}
               </div>
            )}
            
          </div>
        </div>
      )}

      {/* Edit / Create Modal */}
      {editingJob && (
        <div style={{ 
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, 
          background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(5px)', 
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 
        }} onClick={() => setEditingJob(null)}>
          <div style={{ 
            background: 'var(--card)', maxWidth: '700px', width: '95%', maxHeight: '90vh', overflowY: 'auto',
            padding: '2.5rem', borderRadius: '24px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
            border: '1px solid var(--border)', position: 'relative',
            animation: 'fadeInUp 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards'
          }} onClick={e => e.stopPropagation()}>
            <button style={{ 
              position: 'absolute', top: '1.5rem', right: '1.5rem', background: 'var(--bg)', 
              border: 'none', width: '32px', height: '32px', borderRadius: '50%', 
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', color: 'var(--t2)', fontSize: '1.2rem', transition: 'all 0.2s'
            }} onClick={() => setEditingJob(null)}>×</button>
            
            <h2 style={{ fontSize: '1.75rem', marginBottom: '2rem', fontWeight: 800, color: 'var(--t1)' }}>
              {editingJob.id ? 'Edit Job Details' : 'Create New Job'}
            </h2>
            
            <form onSubmit={handleSaveJob}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
                <div style={{ gridColumn: '1 / -1' }}>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Job Title *</label>
                  <input type="text" value={editForm.title} onChange={e => setEditForm({...editForm, title: e.target.value})} required 
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none' }} />
                </div>
                
                <div>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Location</label>
                  <input type="text" value={editForm.location} onChange={e => setEditForm({...editForm, location: e.target.value})} placeholder="e.g. San Francisco, CA" 
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none' }} />
                </div>
                
                <div>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Work Mode</label>
                  <select value={editForm.work_mode} onChange={e => setEditForm({...editForm, work_mode: e.target.value})}
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none' }}>
                    <option>On-site</option>
                    <option>Hybrid</option>
                    <option>Remote</option>
                  </select>
                </div>
                
                <div>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Experience Level</label>
                  <input type="text" value={editForm.experience_level} onChange={e => setEditForm({...editForm, experience_level: e.target.value})} placeholder="e.g. Mid-Level, Senior"
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none' }} />
                </div>
                
                <div>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Salary Range</label>
                  <input type="text" value={editForm.salary_range} onChange={e => setEditForm({...editForm, salary_range: e.target.value})} placeholder="e.g. $100k - $130k"
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none' }} />
                </div>
                
                <div style={{ gridColumn: '1 / -1' }}>
                  <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem', color: 'var(--t2)' }}>Job Description</label>
                  <textarea value={editForm.description} onChange={e => setEditForm({...editForm, description: e.target.value})} rows="5" required
                    style={{ width: '100%', padding: '0.85rem', borderRadius: '10px', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--t1)', outline: 'none', resize: 'vertical' }} />
                </div>
                
                <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '1rem', background: 'var(--bg)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                  <input type="checkbox" id="publish-check" checked={editForm.is_published} onChange={e => setEditForm({...editForm, is_published: e.target.checked})} 
                    style={{ width: '1.2rem', height: '1.2rem', accentColor: 'var(--blue)' }} />
                  <label htmlFor="publish-check" style={{ fontWeight: 600, cursor: 'pointer', color: 'var(--t1)' }}>Publish to Candidate Portal immediately</label>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '2rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem' }}>
                <button type="button" onClick={() => setEditingJob(null)} style={{ 
                  background: 'none', border: '1px solid var(--border)', padding: '0.85rem 1.5rem', 
                  borderRadius: '10px', fontWeight: 600, color: 'var(--t2)', cursor: 'pointer', transition: 'all 0.2s'
                }}>Cancel</button>
                <button type="submit" disabled={saveLoading} style={{ 
                  background: 'var(--blue)', border: 'none', padding: '0.85rem 2rem', 
                  borderRadius: '10px', fontWeight: 600, color: 'white', cursor: 'pointer', 
                  transition: 'all 0.2s', opacity: saveLoading ? 0.7 : 1, boxShadow: '0 4px 12px rgba(59, 130, 246, 0.3)'
                }}>
                  {saveLoading ? 'Saving...' : 'Save Job Posting'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <style dangerouslySetInnerHTML={{__html: `
        @keyframes slideDown {
          from { top: -5rem; opacity: 0; }
          to { top: 2rem; opacity: 1; }
        }
        @keyframes fadeInUp {
          from { transform: translateY(20px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
        .hover-lift:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px rgba(59, 130, 246, 0.4) !important;
        }
        .hover-border:hover {
          border-color: var(--t1) !important;
          color: var(--t1) !important;
        }
        .hover-border-blue:hover {
          border-color: var(--blue) !important;
          background: rgba(4, 120, 87, 0.05) !important;
        }
      `}} />
    </div>
  );
}
