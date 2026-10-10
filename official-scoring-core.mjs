/**
 * LexFlow official-answer reference evaluator, deliberately not a publication
 * or production-scoring authorization. Policies must come from offline source
 * review and are NOT trustworthy if supplied through user uploads / feed JSON.
 * No official question is scorable through this module's application gate.
 */
const ALL = 'ABCDE';
const KINDS = new Set([
  'SINGLE_EXACT', 'MULTIPLE_ACCEPTED_VARIANTS',
  'CORRECTED_SINGLE_REPLACEMENT', 'UNCONDITIONAL_ALL_CREDIT',
  'FIVE_OPTION_PARTIAL_CREDIT'
]);

function assert(ok, why) { if (!ok) throw new Error(why); }
function parseField(value, label) {
  if (typeof value === 'string') {
    assert(value.length < 4096, `${label} too large`);
    try { return JSON.parse(value); } catch { throw new Error(`invalid ${label} JSON`); }
  }
  return value;
}

/** Returns a canonical, uppercase, alphabetical set of marked choices. */
export function normalizeOfficialSelection(value, alphabet = 'ABCD') {
  assert(alphabet === 'ABCD' || alphabet === 'ABCDE', 'invalid alphabet');
  if (value === '' || value === null || value === undefined) return '';
  const choices = Array.isArray(value) ? value : typeof value === 'string' ? [...value] : null;
  assert(choices && choices.length <= alphabet.length, 'invalid answer selection');
  assert(choices.every(letter => typeof letter === 'string' && letter.length === 1 && alphabet.includes(letter)), 'choice out of range');
  assert(new Set(choices).size === choices.length, 'duplicate option mark');
  return [...choices].sort().join('');
}

function validatedRule(rule) {
  assert(rule && typeof rule === 'object' && !Array.isArray(rule), 'missing rule');
  assert(KINDS.has(rule.proposal_mode), 'unknown official rule');
  const mode = rule.proposal_mode;
  const alphabet = mode === 'FIVE_OPTION_PARTIAL_CREDIT' ? 'ABCDE' : 'ABCD';
  const variants = parseField(rule.accepted_variants_json, 'accepted variants');
  assert(Array.isArray(variants) && variants.length <= 32, 'invalid acceptable variants');
  const canonical = variants.map(item => normalizeOfficialSelection(item, alphabet));
  assert(canonical.every(x => x !== ''), 'empty official answer variant');
  assert(canonical.length === new Set(canonical).size, 'repeated variant');
  if (mode === 'SINGLE_EXACT' || mode === 'CORRECTED_SINGLE_REPLACEMENT')
    assert(canonical.length === 1 && canonical[0].length === 1, 'invalid single key');
  if (mode === 'MULTIPLE_ACCEPTED_VARIANTS')
    assert(canonical.length >= 1, 'missing correction variants');
  if (mode === 'UNCONDITIONAL_ALL_CREDIT')
    assert(canonical.length === 0, 'all-credit rule must have no key');
  if (mode === 'FIVE_OPTION_PARTIAL_CREDIT')
    assert(canonical.length === 1, 'five-choice key must be a single set');
  const config = parseField(rule.exceptional_scoring_json, 'partial credit');
  if (mode === 'FIVE_OPTION_PARTIAL_CREDIT') {
    assert(config && typeof config === 'object' && !Array.isArray(config), 'missing partial-credit spec');
    assert(config.option_count === 5 && config.wrong_count_mode === 'SYMMETRIC_DIFFERENCE_MARKED_AND_CORRECT', 'unknown marking method');
    assert(config.points_full === 3 && config.points_one_wrong === 1.8 &&
      config.points_two_wrong === 0.6 && config.points_other === 0 && config.blank_credit === 0,
    'unverified partial-credit schedule');
  } else assert(config === null || config === undefined, 'unexpected partial-credit policy');
  return {mode, alphabet, variants:canonical, config};
}

/** Input controls for future verified tests. Not a claim that official answers are approved. */
export function officialInputSpec(rule) {
  const {mode, alphabet, variants} = validatedRule(rule);
  const multi = mode === 'FIVE_OPTION_PARTIAL_CREDIT' ||
    (mode === 'MULTIPLE_ACCEPTED_VARIANTS' && variants.some(x => x.length > 1));
  return Object.freeze({alphabet, inputType: multi ? 'checkbox' : 'radio',
    allowsMultipleMarks:multi, scoringAvailable:false});
}

/**
 * Audit-only reference output, NEVER an official score. Published interfaces
 * must not use this to mark official exams; they must wait for verified signed
 * release data and independent browser-to-storage E2E testing.
 */
export function scoreOfficialReferenceForAudit(rule, response) {
  const {mode,alphabet,variants,config} = validatedRule(rule);
  const answer = normalizeOfficialSelection(response, alphabet);
  // Unexpected multi-mark responses earn zero, rather than crashing the grader.
  // The UI still prevents them for radio-only exams.
  let earnedUnits, maxUnits = 1;
  if (mode === 'UNCONDITIONAL_ALL_CREDIT') earnedUnits = 1;
  else if (mode === 'FIVE_OPTION_PARTIAL_CREDIT') {
    const key = variants[0];
    const wrong = [...alphabet].filter(letter => key.includes(letter) !== answer.includes(letter)).length;
    maxUnits = config.points_full;
    earnedUnits = answer === '' ? config.blank_credit :
      wrong === 0 ? config.points_full :
      wrong === 1 ? config.points_one_wrong :
      wrong === 2 ? config.points_two_wrong : config.points_other;
  } else earnedUnits = variants.includes(answer) ? 1 : 0;
  return Object.freeze({status:'AUDIT_REFERENCE_ONLY_NOT_AN_OFFICIAL_SCORE',
    earnedUnits, maxUnits, officialScore:null, publicationAllowed:false});
}

/** Public or imported staging must ALWAYS be blocked, regardless of fake flags. */
export function scoreUnreleasedOfficialSession() {
  return Object.freeze({status:'BLOCKED_PENDING_FULL_REVIEW',
    correct:null, percentage:null, officialScore:null, publicationAllowed:false});
}

/** Render-only candidate selection model. Neither a score nor official proof. */
export function previewChoiceSpec(question) {
  const opts = question?.options;
  assert(Array.isArray(opts) && (opts.length === 4 || opts.length === 5), 'invalid review option count');
  assert(opts.every(x => typeof x === 'string' && x.trim()), 'empty review option');
  const multi = opts.length === 5 || question?.answerInputMode === 'multiple';
  assert(question?.answerInputMode === undefined || question?.answerInputMode === 'single' ||
    question?.answerInputMode === 'multiple', 'invalid preview input mode');
  return {alphabet: ALL.slice(0,opts.length), inputType: multi ? 'checkbox':'radio', allowsMultipleMarks:multi};
}

export function canonicalPreviewResponse(value, question) {
  const spec = previewChoiceSpec(question);
  const result = normalizeOfficialSelection(value, spec.alphabet);
  if (!spec.allowsMultipleMarks && result.length > 1) throw new Error('single-choice question');
  return result;
}

export function countPreviewAnswered(responses, questions) {
  assert(responses && typeof responses === 'object' && !Array.isArray(responses) && Array.isArray(questions), 'invalid response state');
  return questions.reduce((n,q) => {
    try { return n + (canonicalPreviewResponse(responses[String(q.number)],q) !== '' ? 1 : 0); }
    catch { return n; }
  },0);
}
