import { useState } from 'react'

const CATEGORY_LABELS = {
  fabricated_citation: 'Fabricated citation',
  doctored_quote: 'Doctored quote',
  mischaracterized_holding: 'Mischaracterized holding',
  cross_document_contradiction: 'Cross-document contradiction',
  unsupported_assertion: 'Unsupported assertion',
  misleading_framing: 'Misleading framing',
  could_not_verify: 'Could not verify',
}

const SEVERITY_COLORS = {
  high: { bg: '#fde8e8', fg: '#9b1c1c', border: '#f8b4b4' },
  medium: { bg: '#fdf6b2', fg: '#8e4b10', border: '#f6e05e' },
  low: { bg: '#e1effe', fg: '#1e429f', border: '#a4cafe' },
}

const STAGE_COLORS = { ok: '#0e9f6e', failed: '#e02424', skipped: '#9ca3af' }

function Badge({ children, colors }) {
  return (
    <span
      style={{
        background: colors.bg,
        color: colors.fg,
        border: `1px solid ${colors.border}`,
        borderRadius: '999px',
        padding: '2px 10px',
        fontSize: '12px',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

function ConfidenceBar({ value }) {
  const pct = Math.round(value * 100)
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
      <span
        style={{
          width: '70px',
          height: '6px',
          background: '#e5e7eb',
          borderRadius: '3px',
          overflow: 'hidden',
          display: 'inline-block',
        }}
      >
        <span
          style={{
            display: 'block',
            width: `${pct}%`,
            height: '100%',
            background: pct >= 80 ? '#0e9f6e' : pct >= 50 ? '#c27803' : '#e02424',
          }}
        />
      </span>
      <span style={{ fontSize: '12px', color: '#6b7280' }}>{pct}%</span>
    </span>
  )
}

function EvidenceList({ evidence }) {
  if (!evidence?.length) return null
  return (
    <div style={{ marginTop: '10px' }}>
      {evidence.map((e, i) => (
        <blockquote
          key={i}
          style={{
            margin: '6px 0',
            padding: '8px 12px',
            borderLeft: '3px solid #d1d5db',
            background: '#f9fafb',
            fontSize: '13px',
            color: '#374151',
          }}
        >
          <div style={{ fontSize: '11px', color: '#9ca3af', marginBottom: '2px' }}>
            {e.document}
          </div>
          “{e.quote}”
        </blockquote>
      ))}
    </div>
  )
}

function FindingCard({ finding }) {
  const sev = SEVERITY_COLORS[finding.severity] ?? SEVERITY_COLORS.low
  const isDup = Boolean(finding.duplicate_of)
  return (
    <div
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: '8px',
        padding: '14px 16px',
        marginBottom: '10px',
        opacity: isDup ? 0.55 : 1,
        background: '#fff',
      }}
    >
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
        <Badge colors={sev}>{finding.severity.toUpperCase()}</Badge>
        <span style={{ fontSize: '12px', color: '#6b7280' }}>
          {CATEGORY_LABELS[finding.category] ?? finding.category}
        </span>
        <span style={{ fontSize: '12px', color: '#9ca3af' }}>· {finding.brief_location}</span>
        <span style={{ marginLeft: 'auto' }}>
          <ConfidenceBar value={finding.confidence} />
        </span>
      </div>
      <div style={{ fontWeight: 600, margin: '8px 0 4px', fontSize: '15px' }}>
        {finding.title}
        {isDup && (
          <span style={{ fontWeight: 400, fontSize: '12px', color: '#9ca3af' }}>
            {' '}(duplicate of {finding.duplicate_of})
          </span>
        )}
      </div>
      <div style={{ fontSize: '14px', color: '#374151', lineHeight: 1.5 }}>
        {finding.description}
      </div>
      <EvidenceList evidence={finding.evidence} />
      <div style={{ marginTop: '8px', fontSize: '11px', color: '#9ca3af' }}>
        {finding.source_agent} · {finding.confidence_reasoning}
      </div>
    </div>
  )
}

function App() {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showCnv, setShowCnv] = useState(false)

  const runAnalysis = async () => {
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const response = await fetch('http://localhost:8002/analyze', { method: 'POST' })
      if (!response.ok) throw new Error(`Server responded with ${response.status}`)
      const data = await response.json()
      setReport(data.report)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const live = report?.findings?.filter((f) => !f.duplicate_of) ?? []
  const dups = report?.findings?.filter((f) => f.duplicate_of) ?? []
  const bySeverity = { high: 0, medium: 0, low: 0 }
  live.forEach((f) => { bySeverity[f.severity] += 1 })

  return (
    <div style={{ maxWidth: '860px', margin: '40px auto', padding: '0 20px', fontFamily: 'system-ui, sans-serif', color: '#111827' }}>
      <h1 style={{ marginBottom: '4px' }}>BS Detector</h1>
      <p style={{ marginTop: 0, color: '#6b7280' }}>
        Legal brief verification pipeline
        {report && ` — ${report.case_caption} (${report.document_analyzed})`}
      </p>

      <button
        onClick={runAnalysis}
        disabled={loading}
        style={{
          padding: '10px 24px',
          fontSize: '16px',
          cursor: loading ? 'not-allowed' : 'pointer',
          background: '#1f2937',
          color: '#fff',
          border: 'none',
          borderRadius: '6px',
        }}
      >
        {loading ? 'Analyzing… (this takes a minute or two)' : 'Run Analysis'}
      </button>

      {error && (
        <div style={{ marginTop: '20px', color: '#9b1c1c' }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {report && (
        <div style={{ marginTop: '28px' }}>
          {report.judicial_memo && (
            <div
              style={{
                border: '1px solid #d1d5db',
                borderRadius: '8px',
                padding: '18px 20px',
                background: '#f9fafb',
                marginBottom: '24px',
              }}
            >
              <div style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '0.05em', color: '#6b7280', marginBottom: '8px' }}>
                BENCH MEMORANDUM
              </div>
              <div style={{ fontSize: '15px', lineHeight: 1.65 }}>{report.judicial_memo}</div>
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', marginBottom: '18px', flexWrap: 'wrap' }}>
            <Badge colors={SEVERITY_COLORS.high}>{bySeverity.high} high</Badge>
            <Badge colors={SEVERITY_COLORS.medium}>{bySeverity.medium} medium</Badge>
            <Badge colors={SEVERITY_COLORS.low}>{bySeverity.low} low</Badge>
            <span style={{ fontSize: '13px', color: '#6b7280', alignSelf: 'center' }}>
              {live.length} findings{dups.length > 0 && `, ${dups.length} duplicates merged`},{' '}
              {report.could_not_verify.length} could not be verified
            </span>
          </div>

          <h2 style={{ fontSize: '18px' }}>Findings</h2>
          {live.map((f) => <FindingCard key={f.finding_id} finding={f} />)}
          {dups.map((f) => <FindingCard key={f.finding_id} finding={f} />)}

          {report.could_not_verify.length > 0 && (
            <div style={{ marginTop: '24px' }}>
              <h2 style={{ fontSize: '18px' }}>
                Could not verify{' '}
                <button
                  onClick={() => setShowCnv(!showCnv)}
                  style={{ fontSize: '13px', border: 'none', background: 'none', color: '#1d4ed8', cursor: 'pointer' }}
                >
                  {showCnv ? 'hide' : `show ${report.could_not_verify.length}`}
                </button>
              </h2>
              <p style={{ fontSize: '13px', color: '#6b7280', marginTop: 0 }}>
                Claims and authorities the pipeline could not check against available
                material. Reported honestly rather than guessed at.
              </p>
              {showCnv &&
                report.could_not_verify.map((f) => (
                  <div
                    key={f.finding_id}
                    style={{ border: '1px dashed #d1d5db', borderRadius: '8px', padding: '10px 14px', marginBottom: '8px', fontSize: '13px' }}
                  >
                    <strong>{f.title}</strong>
                    <span style={{ color: '#9ca3af' }}> · {f.brief_location}</span>
                    <div style={{ color: '#4b5563', marginTop: '4px' }}>{f.description}</div>
                  </div>
                ))}
            </div>
          )}

          <div style={{ marginTop: '28px', borderTop: '1px solid #e5e7eb', paddingTop: '12px' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
              {report.stages.map((s) => (
                <span key={s.name} title={s.error ?? ''}>
                  <span style={{ color: STAGE_COLORS[s.state] }}>●</span> {s.name}{' '}
                  {s.state === 'ok' ? `${(s.duration_ms / 1000).toFixed(1)}s` : s.state}
                </span>
              ))}
            </div>
            <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '6px' }}>
              models: {report.model_fast} (extraction) / {report.model_reasoning} (verification)
            </div>
          </div>
        </div>
      )}

      {report === null && !loading && !error && (
        <p style={{ marginTop: '20px', color: '#888' }}>
          Click "Run Analysis" to verify the motion against the case file.
        </p>
      )}
    </div>
  )
}

export default App
