import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'

/**
 * Investigator page — three modes:
 *
 *   IDLE     candidate picker + prominent CTA
 *   LIVE     the whole space becomes ONE focused stage narrating what
 *            the agent is doing in plain English, with a progress ring
 *   REPORT   compact live-trace strip on top, structured dossier below
 *            (candidate header, trust verdict, career, projects,
 *            findings, sources)
 *
 * Uses the app's own CSS variables so it respects light/dark theming.
 */

// -----------------------------------------------------------------------------
// Static bits
// -----------------------------------------------------------------------------
const CSS = `
@keyframes invFadeIn  { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@keyframes invPulseA  { 0%,100% { box-shadow: 0 0 0 0 rgba(4,120,87,.55); } 50% { box-shadow: 0 0 0 12px rgba(4,120,87,0); } }
@keyframes invDot     { 0%,80%,100% { transform: scale(0); opacity: .3; } 40% { transform: scale(1); opacity: 1; } }
@keyframes invBlink   { 0%,49% { opacity: 1; } 50%,100% { opacity: 0; } }
@keyframes invMeter   { from { width: 0; } to { width: var(--w, 0%); } }
@keyframes invSpin    { from { transform: rotate(0); } to { transform: rotate(360deg); } }
@keyframes invRipple  { 0% { transform: scale(.9); opacity: .55; } 100% { transform: scale(1.6); opacity: 0; } }

.inv-fade      { animation: invFadeIn .35s ease both; }
.inv-active    { animation: invPulseA 1.6s ease-in-out infinite; }
.inv-tdot      { animation: invDot 1.2s ease-in-out infinite; }
.inv-tdot:nth-child(2){ animation-delay: .18s; }
.inv-tdot:nth-child(3){ animation-delay: .36s; }
.inv-caret::after {
  content: "▍"; margin-left: 4px; color: var(--brand-green);
  animation: invBlink 1s steps(1) infinite; display: inline-block;
}
.inv-meter-fill { animation: invMeter .8s ease-out both; }
.inv-spin      { animation: invSpin 1.2s linear infinite; }
.inv-ripple    { position: absolute; inset: 0; border-radius: 50%;
                 border: 3px solid var(--brand-green); animation: invRipple 1.8s ease-out infinite; }
.inv-ripple.d1 { animation-delay: .6s; }
.inv-ripple.d2 { animation-delay: 1.2s; }
`

const PHASES = [
  { key: 'observe',   label: 'Anchoring',    tools: ['fetch_github_profile'] },
  { key: 'evidence',  label: 'Gathering',    tools: ['list_github_repos', 'read_repo_readme'] },
  { key: 'analyze',   label: 'Analyzing',    tools: ['ai_detect', 'consistency_check'] },
  { key: 'flag',      label: 'Flagging',     tools: ['flag_finding'] },
  { key: 'verdict',   label: 'Concluding',   tools: ['finalize_verdict'] },
]
const phaseOfTool = (toolName) => {
  for (const p of PHASES) if (p.tools.includes(toolName)) return p.key
  return null
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------
const badge = (bg, fg, extra = {}) => ({
  display: 'inline-flex', alignItems: 'center', gap: 6,
  background: bg, color: fg,
  padding: '3px 10px', borderRadius: 999, fontSize: 11, fontWeight: 700,
  letterSpacing: 0.4, textTransform: 'uppercase', ...extra,
})

const cardStyle = (extra = {}) => ({
  background: 'var(--card)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--r2, 12px)',
  boxShadow: 'var(--shadow)',
  ...extra,
})

const SEVERITY = {
  critical: { fg: 'var(--red)', bg: 'var(--red-bg)', icon: '🚨', label: 'CRITICAL' },
  high:     { fg: 'var(--red)', bg: 'var(--red-bg)', icon: '🚩', label: 'HIGH' },
  medium:   { fg: 'var(--orange)', bg: 'var(--orange-bg)', icon: '⚠️', label: 'MEDIUM' },
  low:      { fg: 'var(--t3)', bg: 'var(--card-h)', icon: 'ⓘ', label: 'LOW' },
  info:     { fg: 'var(--t3)', bg: 'var(--card-h)', icon: 'ⓘ', label: 'INFO' },
  positive_signal: { fg: 'var(--brand-green)', bg: 'var(--green-bg)', icon: '✅', label: 'POSITIVE' },
}
const styleFor = (f) =>
  SEVERITY[f?.category === 'positive_signal' ? 'positive_signal' : f?.severity] || SEVERITY.info

// -----------------------------------------------------------------------------
// LIVE MODE — the big focused stage
// -----------------------------------------------------------------------------
function LiveStage({ candidate, steps, elapsed }) {
  const visible = steps.filter(s => s.kind !== 'tool_call')
  const latest = visible[visible.length - 1]
  const findings = steps
    .filter(s => s.kind === 'adaptation' || (s.kind === 'observation' && s.tool_name === 'flag_finding'))
    .map(s => s.payload?.finding).filter(Boolean)

  const currentToolStep = [...steps].reverse().find(s => s.kind === 'tool_call')
  const currentPhaseKey = currentToolStep ? phaseOfTool(currentToolStep.tool_name) : null

  const isThought   = latest?.kind === 'thought'
  const headlineTag = isThought ? 'REASONING'
                    : latest?.kind === 'adaptation' ? 'RED FLAG'
                    : latest?.tool_name === 'fetch_github_profile' ? 'VERIFYING IDENTITY'
                    : latest?.tool_name === 'list_github_repos' ? 'READING PUBLIC WORK'
                    : latest?.tool_name === 'read_repo_readme' ? 'INSPECTING A PROJECT'
                    : latest?.tool_name === 'ai_detect' ? 'CHECKING FOR AI TEXT'
                    : latest?.tool_name === 'consistency_check' ? 'AUDITING A CLAIM'
                    : latest?.tool_name === 'flag_finding' ? 'RECORDING A FINDING'
                    : 'INVESTIGATING'

  return (
    <div className="inv-fade" style={{
      ...cardStyle({ padding: '32px 28px' }),
      background: 'linear-gradient(180deg, var(--card) 0%, var(--card-h) 100%)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
        <div style={{ position: 'relative', width: 42, height: 42 }}>
          <div className="inv-ripple" />
          <div className="inv-ripple d1" />
          <div className="inv-ripple d2" />
          <div style={{
            position: 'absolute', inset: 4, borderRadius: '50%',
            background: 'var(--grad)', color: '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 800, fontSize: 15,
          }}>🕵️</div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--brand-green)', letterSpacing: 1 }}>
            LIVE INVESTIGATION · {elapsed}s
          </div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--t1)', marginTop: 2 }}>
            {candidate?.name || 'Candidate'}
          </div>
        </div>
        <div style={badge('var(--brand-green)', '#fff', { padding: '6px 14px', fontSize: 12 })}>
          <span className="inv-tdot" style={{ width: 6, height: 6, borderRadius: '50%', background: '#fff' }} />
          agent working
        </div>
      </div>

      {/* Phase strip */}
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${PHASES.length}, 1fr)`, gap: 10, marginBottom: 26 }}>
        {PHASES.map((p) => {
          const done = visible.some(s => phaseOfTool(s.tool_name) === p.key)
          const active = p.key === currentPhaseKey && !done
          const color = done ? 'var(--brand-green)' : active ? 'var(--brand-green)' : 'var(--t3)'
          return (
            <div key={p.key} style={{
              padding: '10px 12px',
              borderRadius: 8,
              border: `1px solid ${done || active ? 'var(--brand-green)' : 'var(--border)'}`,
              background: done ? 'var(--green-bg)' : active ? 'var(--green-bg)' : 'transparent',
              opacity: done || active ? 1 : 0.55,
              transition: 'all .25s',
            }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, fontWeight: 700, color,
              }}>
                <span
                  className={active ? 'inv-active' : ''}
                  style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: done || active ? 'var(--brand-green)' : 'var(--t3)',
                  }}
                />
                {p.label}
              </div>
            </div>
          )
        })}
      </div>

      {/* Now-happening card */}
      <div style={{
        padding: '22px 24px',
        borderRadius: 12,
        background: 'var(--blue-bg)',
        border: '1px solid var(--brand-green)',
        minHeight: 130,
        display: 'flex', flexDirection: 'column', gap: 10,
      }}>
        <div style={{ fontSize: 10, letterSpacing: 1.5, color: 'var(--brand-green)', fontWeight: 800 }}>
          {headlineTag}
        </div>
        <div
          className={isThought ? 'inv-caret' : ''}
          style={{ fontSize: 17, lineHeight: 1.55, color: 'var(--t1)', fontWeight: 500 }}
        >
          {latest?.content || 'Waking the agent up…'}
        </div>
        {!isThought && latest && (
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--t3)', fontFamily: 'var(--mono)' }}>
            step #{latest.step_index} · {latest.tool_name || latest.kind}
          </div>
        )}
      </div>

      {/* Recent thought trail (small — the previous 4 events, so it feels alive) */}
      <div style={{ marginTop: 18 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t3)', letterSpacing: 0.6, marginBottom: 8 }}>
          RECENT MOVES
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {visible.slice(-5, -1).reverse().map((s) => (
            <div key={s.id} className="inv-fade" style={{
              display: 'flex', gap: 10, alignItems: 'baseline',
              padding: '8px 10px', borderRadius: 6, background: 'var(--card-h)',
              fontSize: 13, color: 'var(--t2)',
            }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--t3)' }}>#{s.step_index}</span>
              <span style={{
                fontSize: 10, fontWeight: 700, color: s.kind === 'adaptation' ? 'var(--red)' : 'var(--t3)',
                letterSpacing: 0.4, minWidth: 68,
              }}>
                {(s.kind === 'thought' ? 'reasoning' : s.kind === 'adaptation' ? 'red flag' : 'evidence').toUpperCase()}
              </span>
              <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {s.content}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Findings ticker */}
      {findings.length > 0 && (
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t3)', letterSpacing: 0.6, marginBottom: 8 }}>
            FINDINGS SO FAR · {findings.length}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {findings.map((f, i) => {
              const s = styleFor(f)
              return (
                <span key={i} className="inv-fade" style={badge(s.bg, s.fg, { textTransform: 'none' })}>
                  {s.icon} <b style={{ fontWeight: 800 }}>{s.label}</b> · {f.note?.slice(0, 60)}
                </span>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// -----------------------------------------------------------------------------
// REPORT MODE — structured dossier
// -----------------------------------------------------------------------------
function TrustDial({ score, tier }) {
  const pct = Math.max(0, Math.min(100, score || 0))
  const color = pct >= 80 ? 'var(--brand-green)'
              : pct >= 65 ? 'var(--brand-green)'
              : pct >= 40 ? 'var(--orange)'
              : 'var(--red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
      <div style={{ position: 'relative', width: 96, height: 96 }}>
        <svg viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)', width: '100%', height: '100%' }}>
          <circle cx="50" cy="50" r="42" fill="none" stroke="var(--border)" strokeWidth="10" />
          <circle cx="50" cy="50" r="42" fill="none" stroke={color} strokeWidth="10"
            strokeDasharray={`${(pct / 100) * 264} 264`} strokeLinecap="round" />
        </svg>
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ fontSize: 26, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums', lineHeight: 1 }}>
            {Math.round(pct)}
          </div>
          <div style={{ fontSize: 10, color: 'var(--t3)', fontWeight: 600, letterSpacing: 0.6 }}>/ 100</div>
        </div>
      </div>
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--t3)', letterSpacing: 0.6 }}>TRUST SCORE</div>
        <div style={{ fontSize: 22, fontWeight: 800, color, marginTop: 2 }}>
          {String(tier || '').replace('_', ' ').toUpperCase() || '—'}
        </div>
      </div>
    </div>
  )
}

function Section({ title, subtitle, children, count }) {
  return (
    <div className="inv-fade" style={{ ...cardStyle({ padding: '20px 22px' }), marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--t1)', letterSpacing: -0.005 }}>
            {title}
            {count != null && (
              <span style={{ marginLeft: 8, fontSize: 12, color: 'var(--t3)', fontWeight: 600 }}>· {count}</span>
            )}
          </h3>
          {subtitle && <div style={{ fontSize: 12, color: 'var(--t3)', marginTop: 2 }}>{subtitle}</div>}
        </div>
      </div>
      {children}
    </div>
  )
}

function CompanyRow({ c, i }) {
  return (
    <div className="inv-fade" style={{
      display: 'grid', gridTemplateColumns: '80px 1fr', gap: 16, alignItems: 'start',
      padding: '14px 0', borderBottom: '1px solid var(--border)',
    }}>
      <div style={{
        fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--t3)', fontWeight: 600,
        letterSpacing: 0.5, paddingTop: 2,
      }}>{c.dates || '—'}</div>
      <div>
        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--t1)' }}>{c.name}</div>
        <div style={{ fontSize: 13, color: 'var(--t2)' }}>{c.role || '(role not stated)'}</div>
        {c.highlights?.length > 0 && (
          <ul style={{ margin: '6px 0 0 18px', padding: 0, fontSize: 12, color: 'var(--t2)', lineHeight: 1.55 }}>
            {c.highlights.slice(0, 3).map((h, j) => <li key={j}>{h}</li>)}
          </ul>
        )}
      </div>
    </div>
  )
}

function ProjectCard({ p }) {
  return (
    <div className="inv-fade" style={{
      padding: 14, borderRadius: 8, background: 'var(--card-h)', border: '1px solid var(--border)',
    }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--t1)' }}>{p.name}</div>
      {p.description && (
        <div style={{ fontSize: 12, color: 'var(--t2)', marginTop: 4, lineHeight: 1.5 }}>
          {p.description}
        </div>
      )}
      {p.tech?.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
          {p.tech.slice(0, 8).map((tech, i) => (
            <span key={i} style={badge('var(--blue-bg)', 'var(--brand-green)', {
              padding: '2px 8px', fontSize: 10, textTransform: 'none', letterSpacing: 0.2, fontWeight: 600,
            })}>{tech}</span>
          ))}
        </div>
      )}
    </div>
  )
}

function FindingRow({ f }) {
  const s = styleFor(f)
  return (
    <div className="inv-fade" style={{
      display: 'flex', gap: 12, padding: '10px 12px',
      background: s.bg, borderRadius: 8, marginBottom: 6,
    }}>
      <div style={{ fontSize: 18, lineHeight: 1 }}>{s.icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 800, color: s.fg, letterSpacing: 0.5 }}>{s.label}</span>
          <span style={{ fontSize: 11, color: 'var(--t3)', fontFamily: 'var(--mono)' }}>{f.category}</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--t1)', lineHeight: 1.5 }}>{f.note}</div>
        {f.evidence && (
          <div style={{ fontSize: 11, color: 'var(--t3)', marginTop: 4, fontStyle: 'italic' }}>
            evidence: {f.evidence}
          </div>
        )}
      </div>
    </div>
  )
}

function Dossier({ report, candidate, elapsed, onReopenTrace }) {
  const profile = report?.profile || {}
  const stored  = report?.candidate || candidate || {}
  const counts  = report?.counts || {}

  return (
    <div>
      {/* Compact live-trace summary strip */}
      <div className="inv-fade" style={{
        ...cardStyle({ padding: '12px 16px' }),
        marginBottom: 14, display: 'flex', alignItems: 'center', gap: 12,
        background: 'var(--green-bg)', border: '1px solid var(--brand-green)',
      }}>
        <span style={{ fontSize: 16 }}>✓</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: 'var(--brand-green)', fontWeight: 700, letterSpacing: 0.5 }}>
            INVESTIGATION COMPLETE · {elapsed}s
          </div>
          <div style={{ fontSize: 13, color: 'var(--t2)', marginTop: 2 }}>
            {report?.summary?.slice(0, 140)}
          </div>
        </div>
        <button onClick={onReopenTrace} style={{
          background: 'transparent', border: '1px solid var(--brand-green)',
          color: 'var(--brand-green)', padding: '6px 12px', borderRadius: 6,
          fontSize: 12, fontWeight: 700, cursor: 'pointer',
        }}>
          Show full trace
        </button>
      </div>

      {/* Candidate header + trust dial */}
      <div className="inv-fade" style={{
        ...cardStyle({ padding: '22px 24px' }),
        marginBottom: 14,
        display: 'grid', gridTemplateColumns: '1fr auto', gap: 20, alignItems: 'center',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <h2 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: 'var(--t1)', letterSpacing: -0.01 }}>
              {stored.name}
            </h2>
            {stored.role && (
              <span style={badge('var(--blue-bg)', 'var(--brand-green)', { textTransform: 'none' })}>
                {stored.role}
              </span>
            )}
          </div>
          {profile.headline && (
            <div style={{ fontSize: 14, color: 'var(--t2)', marginBottom: 8 }}>{profile.headline}</div>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, fontSize: 12, color: 'var(--t3)' }}>
            {stored.email && <span>📧 {stored.email}</span>}
            {profile.location && <span>📍 {profile.location}</span>}
            {stored.github_url && (
              <span>
                <span style={{ color: 'var(--brand-green)', fontFamily: 'var(--mono)' }}>
                  {stored.github_url}
                </span>
              </span>
            )}
          </div>
        </div>
        <TrustDial score={report?.trust_score} tier={report?.tier} />
      </div>

      {/* Two-column: left = career, right = verdict + findings */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
        <div>
          <Section title="Verdict" subtitle="What the agent concluded">
            <p style={{ margin: 0, fontSize: 14, color: 'var(--t2)', lineHeight: 1.6 }}>
              {report?.summary || '—'}
            </p>
            <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              {counts.critical > 0 && <span style={badge('var(--red-bg)', 'var(--red)')}>🚨 {counts.critical} critical</span>}
              {counts.high     > 0 && <span style={badge('var(--red-bg)', 'var(--red)')}>🚩 {counts.high} high</span>}
              {counts.medium   > 0 && <span style={badge('var(--orange-bg)', 'var(--orange)')}>⚠️ {counts.medium} medium</span>}
              {counts.low      > 0 && <span style={badge('var(--card-h)', 'var(--t3)')}>ⓘ {counts.low} low</span>}
              {counts.info     > 0 && <span style={badge('var(--card-h)', 'var(--t3)')}>ⓘ {counts.info} info</span>}
            </div>
          </Section>

          {profile.companies?.length > 0 && (
            <Section title="Career history" subtitle="Extracted from the resume" count={profile.companies.length}>
              {profile.companies.map((c, i) => <CompanyRow key={i} c={c} i={i} />)}
            </Section>
          )}

          {profile.projects?.length > 0 && (
            <Section title="Projects" count={profile.projects.length}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                {profile.projects.map((p, i) => <ProjectCard key={i} p={p} />)}
              </div>
            </Section>
          )}

          {profile.education?.length > 0 && (
            <Section title="Education" count={profile.education.length}>
              {profile.education.map((e, i) => (
                <div key={i} style={{ padding: '8px 0', borderBottom: i < profile.education.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--t1)' }}>{e.school}</div>
                  <div style={{ fontSize: 12, color: 'var(--t2)' }}>
                    {e.degree}{e.year ? ` · ${e.year}` : ''}
                  </div>
                </div>
              ))}
            </Section>
          )}

          {profile.skills?.length > 0 && (
            <Section title="Skills" count={profile.skills.length}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {profile.skills.slice(0, 20).map((s, i) => (
                  <span key={i} style={badge('var(--card-h)', 'var(--t2)', {
                    textTransform: 'none', letterSpacing: 0.1, fontWeight: 600, padding: '4px 10px',
                  })}>{s}</span>
                ))}
              </div>
            </Section>
          )}
        </div>

        <div>
          <Section title="Findings" subtitle="Ranked by severity" count={report?.findings?.length || 0}>
            {(!report?.findings || report.findings.length === 0) && (
              <div style={{ color: 'var(--t3)', fontSize: 13 }}>No specific findings surfaced.</div>
            )}
            {report?.findings?.map((f, i) => <FindingRow key={i} f={f} />)}
          </Section>

          {report?.sources && (
            <Section title="Sources checked">
              <div style={{ fontSize: 13, color: 'var(--t2)' }}>
                <div style={{ marginBottom: 6 }}>
                  <b>GitHub:</b>{' '}
                  {report.sources.github_username
                    ? <span style={{ color: 'var(--brand-green)', fontFamily: 'var(--mono)' }}>@{report.sources.github_username}</span>
                    : <span style={{ color: 'var(--t3)' }}>(none)</span>}
                </div>
                <div><b>Repos read:</b> {report.sources.github_repos_seen ?? 0}</div>
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}

// -----------------------------------------------------------------------------
// Full trace (when user clicks "Show full trace" after done)
// -----------------------------------------------------------------------------
function FullTrace({ steps, onClose }) {
  const visible = steps.filter(s => s.kind !== 'tool_call')
  return (
    <div className="inv-fade" style={{ ...cardStyle({ padding: 16 }), marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Full agent trace</h3>
        <button onClick={onClose} style={{
          marginLeft: 'auto', background: 'transparent', border: '1px solid var(--border)',
          color: 'var(--t2)', padding: '4px 10px', borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}>hide</button>
      </div>
      <div style={{ maxHeight: 360, overflowY: 'auto' }}>
        {visible.map(s => {
          const isThought = s.kind === 'thought'
          const isAdapt   = s.kind === 'adaptation'
          const isFinal   = s.kind === 'final'
          const color = isFinal ? 'var(--brand-green)'
                      : isAdapt ? 'var(--red)'
                      : isThought ? 'var(--brand-green)'
                      : 'var(--t2)'
          const label = isThought ? 'reasoning' : isAdapt ? 'red flag' : isFinal ? 'verdict' : 'evidence'
          return (
            <div key={s.id} style={{
              display: 'grid', gridTemplateColumns: '30px 90px 1fr', gap: 8,
              padding: '8px 4px', borderBottom: '1px solid var(--border)',
              fontSize: 13, color: 'var(--t2)',
            }}>
              <span style={{ fontFamily: 'var(--mono)', color: 'var(--t3)', fontSize: 11 }}>#{s.step_index}</span>
              <span style={{ fontFamily: 'var(--mono)', color, fontSize: 11, fontWeight: 700, letterSpacing: 0.4 }}>{label}</span>
              <span>{s.content}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// -----------------------------------------------------------------------------
// Page
// -----------------------------------------------------------------------------
export default function Investigator() {
  const [candidates, setCandidates] = useState([])
  const [candidateId, setCandidateId] = useState('')
  const [runId, setRunId] = useState(null)
  const [steps, setSteps] = useState([])
  const [status, setStatus] = useState('idle')  // idle | running | done | error
  const [runMeta, setRunMeta] = useState(null)
  const [error, setError] = useState('')
  const [pastRuns, setPastRuns] = useState([])
  const [startedAt, setStartedAt] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [showTrace, setShowTrace] = useState(false)
  const esRef = useRef(null)

  useEffect(() => {
    api.getCandidates().then(setCandidates).catch(e => setError(e.message))
    api.listInvestigations(15).then(setPastRuns).catch(() => {})
  }, [])
  useEffect(() => {
    if (status !== 'running' || !startedAt) return
    const iv = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 500)
    return () => clearInterval(iv)
  }, [status, startedAt])
  useEffect(() => () => { if (esRef.current) esRef.current.close() }, [])

  async function investigate() {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    setError(''); setSteps([]); setRunMeta(null); setShowTrace(false)
    setStartedAt(Date.now()); setElapsed(0); setStatus('running')
    try {
      const { run_id } = await api.startInvestigation(Number(candidateId))
      setRunId(run_id); openStream(run_id)
    } catch (e) { setError(e.message); setStatus('error') }
  }

  function openStream(id) {
    const es = new EventSource(api.investigatorStreamUrl(id))
    esRef.current = es
    es.addEventListener('step', ev => {
      try {
        const step = JSON.parse(ev.data)
        setSteps(prev => prev.some(s => s.id === step.id) ? prev
          : [...prev, step].sort((a, b) => a.step_index - b.step_index))
      } catch {}
    })
    es.addEventListener('done', async () => {
      es.close(); esRef.current = null; setStatus('done')
      try {
        const r = await api.getInvestigation(id)
        setRunMeta(r)
        api.listInvestigations(15).then(setPastRuns).catch(() => {})
      } catch {}
    })
    es.onerror = () => {
      es.close(); esRef.current = null
      api.getInvestigation(id).then(r => {
        setRunMeta(r); setSteps(r.steps || [])
        setStatus(r.status === 'failed' ? 'error' : 'done')
      }).catch(e => { setStatus('error'); setError(e.message) })
    }
  }

  async function reopenPastRun(id) {
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    setError(''); setStatus('done'); setSteps([]); setRunMeta(null); setRunId(id)
    setShowTrace(false); setStartedAt(null); setElapsed(0)
    try {
      const r = await api.getInvestigation(id)
      setRunMeta(r); setSteps(r.steps || [])
      setStatus(r.status === 'failed' ? 'error' : 'done')
      // approximate elapsed from timestamps
      if (r.started_at && r.finished_at) {
        setElapsed(Math.max(1, Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000)))
      }
    } catch (e) { setStatus('error'); setError(e.message) }
  }

  const selectedCand = candidates.find(c => String(c.id) === String(candidateId))
  const report = runMeta?.trust_report || steps.find(s => s.kind === 'final')?.payload?.report

  return (
    <>
      <style>{CSS}</style>
      <div style={{
        padding: '20px 28px 60px', maxWidth: 1280, margin: '0 auto',
        color: 'var(--t1)', fontFamily: 'var(--font)',
      }}>

        {/* Explainer header */}
        <div style={{ ...cardStyle({ padding: '18px 22px', marginBottom: 18, borderLeft: '4px solid var(--brand-green)' }) }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
            <span style={{ fontSize: 22 }}>🕵️</span>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: -0.01 }}>Investigator Agent</h1>
            <span style={{ marginLeft: 'auto', ...badge('var(--green-bg)', 'var(--brand-green)') }}>
              CV & CLAIM VERIFICATION
            </span>
          </div>
          <p style={{ margin: 0, color: 'var(--t2)', fontSize: 14, lineHeight: 1.55, maxWidth: 760 }}>
            Autonomously verifies a candidate's résumé against public evidence — GitHub, AI-generation
            detection, and claim-vs-evidence audits — and produces a structured Trust Report.
          </p>
        </div>

        {/* Controls — always visible so the user can start another */}
        <div style={{ ...cardStyle({ padding: 16 }), marginBottom: 18 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, alignItems: 'end' }}>
            <div style={{ minWidth: 0 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--t3)', marginBottom: 4, fontWeight: 600 }}>
                Candidate
              </label>
              <select value={candidateId} onChange={e => setCandidateId(e.target.value)}
                disabled={status === 'running'}
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--border)',
                  background: 'var(--card)', color: 'var(--t1)', fontSize: 13, fontFamily: 'var(--font)',
                  height: 42, boxSizing: 'border-box',
                }}>
                <option value="">— pick a candidate —</option>
                {candidates.map(c => (
                  <option key={c.id} value={c.id}>
                    #{c.id} · {c.name}{c.role ? ` · ${c.role}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <button onClick={investigate} disabled={!candidateId || status === 'running'}
              style={{
                height: 42, padding: '0 24px', fontWeight: 700, fontSize: 14, letterSpacing: 0.2,
                background: (!candidateId || status === 'running') ? 'var(--t3)' : 'var(--grad)',
                color: '#fff', border: 'none', borderRadius: 10,
                cursor: (!candidateId || status === 'running') ? 'not-allowed' : 'pointer',
                minWidth: 170, boxShadow: 'var(--shadow-glow)', boxSizing: 'border-box',
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              }}>
              {status === 'running' ? `Investigating · ${elapsed}s` : '🕵️ Investigate'}
            </button>
          </div>
          {selectedCand && (
            <div style={{
              marginTop: 10, fontSize: 12, color: 'var(--t3)',
              display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center',
            }}>
              <span>📧 {selectedCand.email || 'no email'}</span>
              {selectedCand.github_url && (
                <span style={{ color: 'var(--brand-green)', fontFamily: 'var(--mono)' }}>
                  {selectedCand.github_url}
                </span>
              )}
            </div>
          )}
        </div>

        {error && (
          <div style={{ background: 'var(--red-bg)', color: 'var(--red)', padding: 12, borderRadius: 8, marginBottom: 12, fontSize: 13 }}>
            {error}
          </div>
        )}

        {/* Mode-switched body */}
        {status === 'running' && (
          <LiveStage candidate={selectedCand || runMeta?.trust_report?.candidate} steps={steps} elapsed={elapsed} />
        )}

        {status === 'done' && report && (
          <>
            {showTrace && <FullTrace steps={steps} onClose={() => setShowTrace(false)} />}
            <Dossier
              report={report}
              candidate={selectedCand || report?.candidate}
              elapsed={elapsed}
              onReopenTrace={() => setShowTrace(v => !v)}
            />
          </>
        )}

        {status === 'idle' && (
          <>
            {/* Past investigations */}
            <div style={{ ...cardStyle({ padding: 0, overflow: 'hidden' }) }}>
              <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Past investigations</h3>
              </div>
              {pastRuns.length === 0 && (
                <div style={{ padding: 20, color: 'var(--t3)', fontSize: 13, textAlign: 'center' }}>
                  Investigate a candidate to see reports here.
                </div>
              )}
              {pastRuns.map(r => {
                const rep = r.trust_report
                const score = rep?.trust_score
                const scoreColor = score == null ? 'var(--t3)'
                  : score >= 65 ? 'var(--brand-green)' : score >= 40 ? 'var(--orange)' : 'var(--red)'
                return (
                  <div key={r.id} onClick={() => reopenPastRun(r.id)}
                    style={{
                      padding: '12px 18px', borderBottom: '1px solid var(--border)',
                      cursor: 'pointer', display: 'flex', gap: 12, alignItems: 'center',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--card-h)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                    <div style={{
                      width: 44, height: 44, borderRadius: '50%',
                      background: scoreColor, color: '#fff',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 800, fontSize: 15, fontVariantNumeric: 'tabular-nums', flexShrink: 0,
                    }}>{score != null ? Math.round(score) : '—'}</div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--t1)' }}>
                        {rep?.candidate_name || `Run #${r.id}`}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--t3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.outcome_summary || 'no summary'}
                      </div>
                    </div>
                    <div style={{
                      ...badge(scoreColor === 'var(--brand-green)' ? 'var(--green-bg)'
                              : scoreColor === 'var(--orange)' ? 'var(--orange-bg)' : 'var(--red-bg)',
                              scoreColor),
                    }}>
                      {rep?.tier ? rep.tier.replace('_', ' ') : r.status}
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </>
  )
}
