import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Project = { id: number; name: string; description: string | null }
type Target = { id: number; name: string; base_url: string; configuration: TargetConfig; credential_names?: string[] }
type TargetConfig = {
  limits?: Record<string, number>
  extra_domains?: string[]
  exclude_url_patterns?: string[]
  forbidden_action_patterns?: string[]
  constraints?: string
}
type Page = {
  id: number; title: string; url: string; exploration_status: string
  discovered_elements: unknown[]; console_errors: unknown[]; failed_requests: unknown[]
}
type Campaign = {
  id: number; target_application_id: number; objective: string | null; status: string
  task_stage: string; task_message: string; task_progress: number; error_message: string | null
  created_at: string
}
type Step = {
  action: string; parameters: { target?: { strategy: string; value: string }; value?: string
    expect?: { type: string; value: string } | null }; expected_observation?: string
}
type Scenario = {
  id: number; title: string; objective: string | null; preconditions: string | null
  expected_result: string | null; approval_status: string; source: string; kind: string; steps: Step[]
}
type Outcome = { step_order: number; action: string; status: string; message: string }
type Result = { status: string; actual_result: string; step_outcomes: Outcome[]
  analysis: { explanation?: string; hypothesis?: string } | null
  evidences: { id: number; type: string }[] }
type Results = { executed: number; success_rate: number; counts: Record<string, number>; by_scenario: Record<number, Result> }

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    ...(body === undefined ? {} : {
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) throw new Error(payload?.error ?? `API indisponible (HTTP ${response.status})`)
  return payload as T
}

const labels: Record<string, string> = {
  created: 'Créée', exploring: 'Exploration', explored: 'Explorée', generating: 'Génération',
  scenarios_ready: 'Scénarios prêts', executing: 'Exécution', completed: 'Terminée', failed: 'En erreur',
  pending: 'À approuver', approved: 'Approuvé', disabled: 'Désactivé', modified: 'Modifié',
}
const limitFields = [
  ['max_pages', 'Pages', 15], ['max_depth', 'Profondeur', 3],
  ['max_duration_seconds', 'Durée (s)', 120], ['max_actions', 'Actions', 100],
] as const
const configFields = [
  ['extra_domains', 'Domaines supplémentaires'], ['exclude_url_patterns', 'URL à exclure'],
  ['forbidden_action_patterns', 'Actions à interdire'],
] as const
const input = (form: FormData, name: string) => String(form.get(name) ?? '').trim()
const list = (form: FormData, name: string) => input(form, name).split(/[\n,]/).map(s => s.trim()).filter(Boolean)
const label = (value: string) => labels[value] ?? value
const running = (campaign: Campaign | null) => Boolean(campaign &&
  (campaign.task_stage === 'queued' || ['exploring', 'generating', 'executing'].includes(campaign.status)))

function CredentialFields({ names }: { names: string[] }) {
  const [rows, setRows] = useState(0)
  return <details>
    <summary>Identifiants de test</summary>
    <p className="muted">Utilisez des comptes de test. Dans l’objectif et les étapes, écrivez le nom de la variable entre accolades, par exemple <code>{'{account_1_password}'}</code>.</p>
    {names.map(name => <fieldset key={name}>
      <legend><code>{'{' + name + '}'}</code></legend>
      <label>Nouvelle valeur<input type="password" name={`replace:${name}`} autoComplete="off" placeholder="Laisser vide pour conserver" /></label>
      <label className="check"><input type="checkbox" name={`remove:${name}`} /> Supprimer cette variable</label>
    </fieldset>)}
    {Array.from({ length: rows }, (_, index) => <div className="fields" key={index}>
      <label>Nom de variable<input name={`credential-name-${index}`} pattern="[A-Za-z_][A-Za-z0-9_]*" placeholder="account_1_email" /></label>
      <label>Valeur<input type="password" name={`credential-value-${index}`} autoComplete="off" /></label>
    </div>)}
    <button type="button" onClick={() => setRows(count => count + 1)}>Ajouter une variable</button>
  </details>
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [project, setProject] = useState<Project & { targets: Target[] } | null>(null)
  const [target, setTarget] = useState<Target | null>(null)
  const [history, setHistory] = useState<Campaign[]>([])
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [pages, setPages] = useState<Page[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [results, setResults] = useState<Results | null>(null)
  const [editor, setEditor] = useState<'project-new' | 'project-edit' | 'target-new' | 'target-edit' | null>(null)
  const [tab, setTab] = useState('exploration')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [editingScenario, setEditingScenario] = useState<number | null>(null)
  const [refresh, setRefresh] = useState(0)

  async function run(work: () => Promise<void>) {
    setBusy(true)
    setError('')
    try { await work() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function loadProjects() { setProjects(await api<Project[]>('/projects')) }
  async function loadHistory() { setHistory(await api<Campaign[]>('/campaigns')) }

  useEffect(() => {
    void run(async () => {
      await Promise.all([loadProjects(), loadHistory()])
    })
  }, [])

  const campaignId = campaign?.id
  const isRunning = running(campaign)
  useEffect(() => {
    if (!campaignId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const data = await api<Campaign>(`/campaigns/${campaignId}`)
        if (cancelled) return
        setCampaign(data)
        if (running(data)) {
          timer = setTimeout(poll, 1100)
        } else {
          const [observations, suite, summary, campaigns] = await Promise.all([
            api<Page[]>(`/campaigns/${campaignId}/exploration`),
            api<Scenario[]>(`/campaigns/${campaignId}/scenarios`),
            api<Results>(`/campaigns/${campaignId}/results`),
            api<Campaign[]>('/campaigns'),
          ])
          if (!cancelled) {
            setPages(observations)
            setScenarios(suite)
            setResults(summary)
            setHistory(campaigns)
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
          if (isRunning) timer = setTimeout(poll, 2500)
        }
      }
    }
    void poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [campaignId, isRunning, refresh])

  function clearCampaign() {
    setCampaign(null)
    setPages([])
    setScenarios([])
    setResults(null)
    setEditingScenario(null)
    setTab('exploration')
  }

  async function selectProject(id: number) {
    const selected = await api<Project & { targets: Target[] }>(`/projects/${id}`)
    setProject(selected)
    setTarget(null)
    setEditor(null)
    clearCampaign()
  }

  function selectTarget(selected: Target) {
    setTarget(selected)
    setEditor(null)
    clearCampaign()
  }

  async function saveProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await run(async () => {
      const editing = editor === 'project-edit' && project
      const saved = await api<Project>(editing ? `/projects/${project.id}` : '/projects',
        editing ? 'PUT' : 'POST', { name: input(form, 'name'), description: input(form, 'description') })
      if (editing) {
        setProject({ ...project, ...saved })
        setEditor(null)
      } else {
        await selectProject(saved.id)
      }
      await loadProjects()
    })
  }

  async function saveTarget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!project) return
    const form = new FormData(event.currentTarget)
    await run(async () => {
      const editing = editor === 'target-edit' && target
      const credentialChanges = new Map<string, string | null>()
      const savedNames = editing ? (target.credential_names ?? []) : []
      for (const name of savedNames) {
        const replacement = String(form.get(`replace:${name}`) ?? '')
        if (form.has(`remove:${name}`)) credentialChanges.set(name, null)
        else if (replacement) credentialChanges.set(name, replacement)
      }
      for (const [key, entry] of form.entries()) {
        if (!key.startsWith('credential-name-')) continue
        const name = String(entry).trim()
        const value = String(form.get(key.replace('name', 'value')) ?? '')
        if (!name && !value) continue
        if (!name || !value) throw new Error('Indiquez un nom et une valeur pour chaque variable.')
        if (savedNames.includes(name) || credentialChanges.has(name)) throw new Error(`Variable déjà utilisée : ${name}`)
        credentialChanges.set(name, value)
      }
      const configuration = {
        ...(editing ? target.configuration : {}),
        credentials: Object.fromEntries(credentialChanges),
        limits: Object.fromEntries(limitFields.map(([key]) => [key, Number(input(form, key))])),
        ...Object.fromEntries(configFields.map(([key]) => [key, list(form, key)])),
        constraints: input(form, 'constraints'),
      }
      const saved = await api<Target>(editing ? `/targets/${target.id}` : `/projects/${project.id}/targets`,
        editing ? 'PUT' : 'POST', { name: input(form, 'name'), base_url: input(form, 'base_url'), configuration })
      const updated = await api<Project & { targets: Target[] }>(`/projects/${project.id}`)
      setProject(updated)
      if (editing) {
        setTarget(saved)
        setEditor(null)
      } else {
        selectTarget(saved)
      }
    })
  }

  async function deleteSelection(kind: 'project' | 'target') {
    const item = kind === 'project' ? project : target
    if (!item || !confirm(`Supprimer « ${item.name} » et ses campagnes ?`)) return
    await run(async () => {
      await api(`/${kind}s/${item.id}`, 'DELETE')
      clearCampaign()
      setTarget(null)
      setEditor(null)
      if (kind === 'target' && project) await selectProject(project.id)
      else setProject(null)
      await Promise.all([loadProjects(), loadHistory()])
    })
  }

  async function createCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!target) return
    const form = new FormData(event.currentTarget)
    await run(async () => {
      const created = await api<Campaign>(`/targets/${target.id}/campaigns`, 'POST', { objective: input(form, 'objective') })
      clearCampaign()
      setCampaign(created)
    })
  }

  async function start(action: string) {
    if (!campaignId) return
    await run(async () => {
      await api(`/campaigns/${campaignId}/${action}`, 'POST')
      setCampaign(await api<Campaign>(`/campaigns/${campaignId}`))
      setRefresh(value => value + 1)
      if (action === 'generate-scenarios') setTab('scenarios')
      if (action === 'execute') setTab('results')
    })
  }

  async function scenarioAction(path: string, method: string, body?: unknown) {
    if (!campaignId) return
    await api(path, method, body)
    setScenarios(await api<Scenario[]>(`/campaigns/${campaignId}/scenarios`))
  }

  async function saveScenario(event: FormEvent<HTMLFormElement>, scenario: Scenario) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await run(async () => {
      let steps: unknown
      try { steps = JSON.parse(String(form.get('steps'))) }
      catch { throw new Error('Les étapes doivent être un tableau JSON valide.') }
      await scenarioAction(`/scenarios/${scenario.id}`, 'PUT', {
        title: input(form, 'title'), objective: input(form, 'objective'),
        preconditions: input(form, 'preconditions'), expected_result: input(form, 'expected_result'), steps,
      })
      setEditingScenario(null)
    })
  }

  const projectDraft = editor === 'project-edit' ? project : null
  const targetDraft = editor === 'target-edit' ? target : null
  const credentialNames = target?.credential_names ?? []
  const locked = busy || isRunning
  const approvals = scenarios.filter(s => s.approval_status === 'approved').length

  return <>
    <header className="top"><div className="brand"><span className="mark" aria-hidden="true">▣</span> Agent E2E</div></header>
    <div className="layout">
      <aside className="sidebar">
        <div className="between"><h2>Projets</h2><button className="small" onClick={() => setEditor('project-new')} disabled={busy}>+ Nouveau</button></div>
        {projects.length === 0 && <p className="muted">Aucun projet.</p>}
        {projects.map(item => <button key={item.id} className={`nav ${project?.id === item.id ? 'selected' : ''}`}
          disabled={busy} onClick={() => void run(() => selectProject(item.id))}>{item.name}</button>)}
        {project && <>
          <div className="between section"><h2>Cibles</h2><button className="small" onClick={() => setEditor('target-new')} disabled={busy}>+ Ajouter</button></div>
          {project.targets.length === 0 && <p className="muted">Aucune cible.</p>}
          {project.targets.map(item => <button key={item.id} className={`nav ${target?.id === item.id ? 'selected' : ''}`}
            disabled={busy} onClick={() => selectTarget(item)}>{item.name}</button>)}
        </>}
        {target && <div className="section"><h2>Historique</h2>
          {history.filter(item => item.target_application_id === target.id).map(item =>
            <button key={item.id} className={`nav ${campaignId === item.id ? 'selected' : ''}`} disabled={busy}
              onClick={() => { if (campaignId !== item.id) { clearCampaign(); setCampaign(item) } }}>
              Campagne #{item.id} <small>{label(item.status)}</small>
            </button>)}
        </div>}
      </aside>
      <main>
        {error && <div role="alert" className="alert">{error} <button className="small" onClick={() => setError('')}>Fermer</button></div>}
        {editor?.startsWith('project') && <section className="panel">
          <h1>{projectDraft ? 'Modifier le projet' : 'Nouveau projet'}</h1>
          <form key={editor} onSubmit={saveProject}>
            <label>Nom<input name="name" required maxLength={200} defaultValue={projectDraft?.name} /></label>
            <label>Description<textarea name="description" defaultValue={projectDraft?.description ?? ''} /></label>
            <div className="actions"><button className="primary" disabled={busy}>Enregistrer</button><button type="button" onClick={() => setEditor(null)}>Annuler</button></div>
          </form>
        </section>}
        {editor?.startsWith('target') && <section className="panel">
          <h1>{targetDraft ? 'Modifier la cible' : 'Nouvelle cible'}</h1>
          <form key={editor} onSubmit={saveTarget}>
            <div className="fields"><label>Nom<input name="name" required maxLength={200} defaultValue={targetDraft?.name} /></label>
              <label>URL de départ<input name="base_url" type="url" required defaultValue={targetDraft?.base_url} placeholder="http://127.0.0.1:5001/" /></label></div>
            <fieldset><legend>Limites de campagne</legend><div className="limits">
              {limitFields.map(([key, title, value]) => <label key={key}>{title}<input name={key} type="number" min={1} required defaultValue={targetDraft?.configuration.limits?.[key] ?? value} /></label>)}
            </div></fieldset>
            <CredentialFields names={targetDraft?.credential_names ?? []} />
            <details><summary>Contraintes et périmètre</summary>
              {configFields.map(([key, title]) => <label key={key}>{title}<textarea name={key} placeholder="Une valeur par ligne" defaultValue={targetDraft?.configuration[key]?.join('\n')} /></label>)}
              <label>Instructions pour la génération<textarea name="constraints" defaultValue={targetDraft?.configuration.constraints} /></label>
            </details>
            <div className="actions"><button className="primary" disabled={busy}>Enregistrer</button><button type="button" onClick={() => setEditor(null)}>Annuler</button></div>
          </form>
        </section>}
        {!editor && !project && <section className="panel empty"><h1>Campagnes de test E2E</h1><p>Créez un projet ou choisissez-en un pour configurer une application à tester.</p>
          <button className="primary" onClick={() => setEditor('project-new')} disabled={busy}>Créer un projet</button></section>}
        {!editor && project && <>
          <div className="between heading">
            <div><p className="muted breadcrumb">{target ? project.name : 'Projet'}</p><h1>{target?.name ?? project.name}</h1>
              <p className="muted break">{target?.base_url ?? project.description}</p></div>
            <div className="actions"><button disabled={locked} onClick={() => setEditor(target ? 'target-edit' : 'project-edit')}>Modifier</button>
              <button className="danger" disabled={locked} onClick={() => void deleteSelection(target ? 'target' : 'project')}>Supprimer</button></div>
          </div>
          {!target && <section className="panel"><h2>Applications cibles</h2>
            {project.targets.map(item => <button key={item.id} className="target-row" onClick={() => selectTarget(item)}>{item.name}<small>{item.base_url}</small></button>)}
            <button className="primary" onClick={() => setEditor('target-new')}>Ajouter une cible</button>
          </section>}
          {target && !campaign && <section className="panel"><h2>Nouvelle campagne</h2>
            <form onSubmit={createCampaign}>
              {credentialNames.length > 0 && <p className="muted">Variables disponibles · {credentialNames.map(name => <code key={name}> {'{' + name + '}'}</code>)}</p>}
              <label>Objectif facultatif<textarea name="objective" placeholder="Vérifier la validation du formulaire d’inscription" /></label>
              <button className="primary" disabled={busy}>Créer la campagne</button>
            </form></section>}
          {campaign && <>
            <section className="panel">
              <div className="between"><h2>Campagne #{campaign.id}</h2><span className="pill">{label(campaign.status)}</span></div>
              {campaign.objective && <p>{campaign.objective}</p>}
              <p role="status" className="muted">{campaign.task_message}</p>
              {isRunning && <progress aria-label="Progression de la campagne" max="100" value={campaign.task_progress} />}
              {campaign.error_message && <p className="alert">{campaign.error_message}</p>}
              <div className="actions">
                {['created', 'failed'].includes(campaign.status) && <button className="primary" disabled={locked} onClick={() => void start('explore')}>Explorer la cible</button>}
                {['explored', 'failed'].includes(campaign.status) && pages.length > 0 && scenarios.length === 0 &&
                  <button className="primary" disabled={locked} onClick={() => void start('generate-scenarios')}>Générer les scénarios</button>}
                {approvals > 0 && ['scenarios_ready', 'completed', 'failed'].includes(campaign.status) &&
                  <button className="primary" disabled={locked} onClick={() => void start('execute')}>Exécuter les scénarios approuvés ({approvals})</button>}
                <button disabled={busy} onClick={clearCampaign}>Nouvelle campagne</button>
              </div>
            </section>
            <nav className="tabs" aria-label="Détails de la campagne">
              {[['exploration', 'Exploration'], ['scenarios', 'Scénarios'], ['results', 'Résultats']].map(([key, title]) =>
                <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{title}</button>)}
            </nav>
            {tab === 'exploration' && <section className="panel"><h2>Pages observées ({pages.length})</h2>
              {pages.length === 0 && <p className="muted">Aucune page enregistrée.</p>}
              {pages.map(page => <details key={page.id}><summary>{page.title || page.url} <small>{page.discovered_elements.length} éléments</small></summary>
                <p className="break">{page.url} · {page.exploration_status}</p>
                <pre>{JSON.stringify(page.discovered_elements, null, 2)}</pre>
                {(page.console_errors.length > 0 || page.failed_requests.length > 0) &&
                  <pre>{JSON.stringify({ console: page.console_errors, réseau: page.failed_requests }, null, 2)}</pre>}
              </details>)}</section>}
            {tab === 'scenarios' && <section className="panel"><div className="between"><h2>Scénarios ({scenarios.length})</h2>
              {scenarios.some(s => s.approval_status === 'pending') && <button disabled={locked} onClick={() => void run(() =>
                scenarioAction(`/campaigns/${campaignId}/scenarios/approve-all`, 'POST'))}>Approuver les scénarios en attente</button>}</div>
              {scenarios.length === 0 && <p className="muted">Aucun scénario généré.</p>}
              {scenarios.map(scenario => <article className="item" key={scenario.id}>
                <div className="between"><h3>{scenario.title}</h3><span className="pill">{label(scenario.approval_status)}</span></div>
                <p className="muted">{scenario.kind === 'negative' ? 'Test négatif' : 'Test positif'} · {scenario.source === 'hypothesis' ? 'Hypothèse' : 'Observation'}</p>
                {editingScenario === scenario.id ? <form onSubmit={event => void saveScenario(event, scenario)}>
                  <label>Titre<input name="title" required defaultValue={scenario.title} /></label>
                  <label>Objectif<textarea name="objective" defaultValue={scenario.objective ?? ''} /></label>
                  <label>Préconditions<textarea name="preconditions" defaultValue={scenario.preconditions ?? ''} /></label>
                  <label>Résultat attendu<textarea name="expected_result" defaultValue={scenario.expected_result ?? ''} /></label>
                  <label>Étapes (JSON)<textarea className="code" rows={12} name="steps" required defaultValue={JSON.stringify(
                    scenario.steps.map(step => ({ action: step.action, ...step.parameters, expected_observation: step.expected_observation })), null, 2)} /></label>
                  <p className="muted">Pour relever un total, utilisez <code>read_text</code> et ciblez l’élément qui l’affiche. Le texte relevé apparaît dans le rapport.</p>
                  <div className="actions"><button className="primary" disabled={locked}>Enregistrer</button><button type="button" onClick={() => setEditingScenario(null)}>Annuler</button></div>
                </form> : <>
                  {scenario.objective && <p>{scenario.objective}</p>}
                  {scenario.preconditions && <p className="muted">{scenario.preconditions}</p>}
                  {scenario.expected_result && <p><strong>Résultat attendu</strong> {scenario.expected_result}</p>}
                  <details><summary>Étapes ({scenario.steps.length})</summary><ol>{scenario.steps.map((step, index) =>
                    <li key={index}><strong>{step.action}</strong> {step.parameters.target?.value} {step.expected_observation && <small>· {step.expected_observation}</small>}</li>)}</ol></details>
                  <div className="actions">
                    <button disabled={locked} onClick={() => setEditingScenario(scenario.id)}>Modifier</button>
                    {scenario.approval_status !== 'approved' && <button disabled={locked} onClick={() => void run(() =>
                      scenarioAction(`/scenarios/${scenario.id}/approval`, 'POST', { status: 'approved' }))}>Approuver</button>}
                    {scenario.approval_status !== 'disabled' && <button disabled={locked} onClick={() => void run(() =>
                      scenarioAction(`/scenarios/${scenario.id}/approval`, 'POST', { status: 'disabled' }))}>Désactiver</button>}
                    <button className="danger" disabled={locked} onClick={() => {
                      if (confirm(`Supprimer « ${scenario.title} » ?`)) void run(() => scenarioAction(`/scenarios/${scenario.id}`, 'DELETE'))
                    }}>Supprimer</button>
                  </div>
                </>}
              </article>)}
            </section>}
            {tab === 'results' && <section className="panel"><h2>Résultats</h2>
              {isRunning ? <p className="muted">La campagne est en cours.</p> : !results?.executed ? <p className="muted">Aucun résultat enregistré.</p> : <>
                <div className="metrics"><strong>{results.executed} exécutés</strong><strong>{results.success_rate} % réussis</strong>
                  {Object.entries(results.counts).map(([status, count]) => <span key={status} className="pill">{status} {count}</span>)}</div>
                <div className="actions">
                  <a className="button" target="_blank" rel="noreferrer" href={`/api/campaigns/${campaignId}/report`}>Consulter le rapport</a>
                  <a className="button" href={`/api/campaigns/${campaignId}/report/download`}>Télécharger le HTML</a>
                </div>
                {Object.entries(results.by_scenario).map(([id, result]) => <article key={id} className="item">
                  <div className="between"><h3>{scenarios.find(s => String(s.id) === id)?.title ?? `Scénario #${id}`}</h3><span className="pill">{result.status}</span></div>
                  <p>{result.actual_result}</p>
                  {result.analysis?.explanation && <p>{result.analysis.explanation}</p>}
                  {result.analysis?.hypothesis && <p className="muted">Cause possible · {result.analysis.hypothesis}</p>}
                  <details><summary>Étapes exécutées</summary><ol>{result.step_outcomes.map(step =>
                    <li key={step.step_order}>{step.status} · {step.action} · {step.message}</li>)}</ol></details>
                  <div className="actions">{result.evidences.map(evidence => <a key={evidence.id} target="_blank" rel="noreferrer"
                    href={`/api/evidences/${evidence.id}/file`}>{evidence.type} #{evidence.id}</a>)}</div>
                </article>)}
              </>}
            </section>}
          </>}
        </>}
      </main>
    </div>
  </>
}

createRoot(document.getElementById('app')!).render(<App />)
