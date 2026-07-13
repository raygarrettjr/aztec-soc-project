const Anthropic = require("@anthropic-ai/sdk");
const { getPool } = require("./lib/db");
const { SYSTEM_PROMPT } = require("./lib/instructions");
const {
  loadOnetFile,
  parseRelatedOccupations,
  resolveNaicsTitle,
  loadTargetSocs,
} = require("./lib/reference");

// Vercel's Hobby tier gives serverless functions a 30-second default timeout
// (and up to 300 seconds with Fluid Compute), well beyond Netlify's 10-second
// ceiling, so these can be more generous than the Netlify version was forced
// to be. Still kept configurable in case real-world latency needs tuning.
const SAMPLE_SIZE = Number(process.env.DUTY_SAMPLE_SIZE || 200);
const RFI_SAMPLE_SIZE = Number(process.env.RFI_SAMPLE_SIZE || 10);
const MAX_DUTY_TEXT_CHARS = Number(process.env.MAX_DUTY_TEXT_CHARS || 400);
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-5";

module.exports = async (req, res) => {
  try {
    if (req.method !== "POST") {
      return res.status(405).json({ error: "Use POST." });
    }
    const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : (req.body || {});
    const soc = body.soc;
    const naicsCodes = Array.isArray(body.naicsCodes) && body.naicsCodes.length ? body.naicsCodes : null;

    const targetSocs = loadTargetSocs();
    const socEntry = targetSocs.find((s) => s.soc_code === soc);
    if (!socEntry) {
      return res.status(400).json({ error: "Unknown or missing SOC code." });
    }

    const pool = getPool();
    const naicsFilter = naicsCodes ? "AND naics_code = ANY($2::text[])" : "";
    const params = naicsCodes ? [soc, naicsCodes] : [soc];

    // 1. Total filings + usable job duties count
    const countsQ = await pool.query(
      `SELECT count(*) AS total,
              count(*) FILTER (WHERE job_duties IS NOT NULL AND job_duties != '') AS usable
       FROM h2b_cases WHERE soc_code = $1 ${naicsFilter}`,
      params
    );
    const totalFilings = Number(countsQ.rows[0].total);
    const usableDuties = Number(countsQ.rows[0].usable);

    // 2. Sample of real job_duties text
    const sampleQ = await pool.query(
      `SELECT case_number, job_duties FROM h2b_cases
       WHERE soc_code = $1 ${naicsFilter} AND job_duties IS NOT NULL AND job_duties != ''
       ORDER BY random() LIMIT ${SAMPLE_SIZE}`,
      params
    );

    // 3. RFI-flagged snippets
    const rfiQ = await pool.query(
      `SELECT case_number, job_duties FROM h2b_cases
       WHERE soc_code = $1 ${naicsFilter}
         AND (job_duties ILIKE '%RFI%' OR job_duties ILIKE '%request for information%')
       ORDER BY random() LIMIT ${RFI_SAMPLE_SIZE}`,
      params
    );

    // 4. Wage average for this SOC (+ NAICS scope)
    const wageQ = await pool.query(
      `SELECT count(*) AS n, round(avg(wage_from)::numeric, 2) AS avg_wage
       FROM h2b_cases WHERE soc_code = $1 ${naicsFilter} AND wage_from IS NOT NULL`,
      params
    );

    // 5. O*NET reference + related occupations
    const onetText = loadOnetFile(soc);
    const related = parseRelatedOccupations(onetText);
    const relatedInTargetSet = related.filter((r) => targetSocs.some((t) => t.soc_code === r.soc_code));
    const relatedWithOnetFile = related.filter((r) => loadOnetFile(r.soc_code) && !relatedInTargetSet.includes(r));
    const relatedNoData = related.filter(
      (r) => !relatedInTargetSet.includes(r) && !relatedWithOnetFile.includes(r)
    );

    let relatedWageRows = [];
    if (relatedInTargetSet.length) {
      const codes = relatedInTargetSet.map((r) => r.soc_code);
      const relQ = await pool.query(
        `SELECT soc_code, soc_title, count(*) AS n, round(avg(wage_from)::numeric, 2) AS avg_wage
         FROM h2b_cases WHERE soc_code = ANY($1::text[]) AND wage_from IS NOT NULL
         GROUP BY soc_code, soc_title`,
        [codes]
      );
      relatedWageRows = relQ.rows;
    }

    const naicsTitle = naicsCodes ? resolveNaicsTitle(naicsCodes[0]) : null;

    // Build the user message with all retrieved real data
    const parts = [];
    parts.push(`SOC code: ${soc}`);
    parts.push(`SOC title: ${socEntry.soc_title}`);
    if (naicsTitle) parts.push(`NAICS scope selected by user: ${naicsTitle} (codes: ${naicsCodes.join(", ")})`);
    parts.push(`Total filings for this SOC${naicsTitle ? " and NAICS scope" : ""}: ${totalFilings}`);
    parts.push(`Filings with usable job duties text: ${usableDuties} (${totalFilings ? ((usableDuties / totalFilings) * 100).toFixed(1) : "0.0"}%)`);
    parts.push(`Average wage_from for this SOC scope: ${wageQ.rows[0].avg_wage || "not available"} (based on ${wageQ.rows[0].n} filings with wage data)`);

    const truncate = (s, n) => (s && s.length > n ? s.slice(0, n) + "..." : s);

    parts.push(`\n--- Sample of ${sampleQ.rows.length} real job_duties entries for this SOC${naicsTitle ? "/NAICS scope" : ""} (use this to estimate duty and tool phrase frequency) ---`);
    sampleQ.rows.forEach((r, i) => {
      parts.push(`[${i + 1}] (case ${r.case_number}): ${truncate(r.job_duties, MAX_DUTY_TEXT_CHARS)}`);
    });

    parts.push(`\n--- RFI-flagged snippets found for this SOC${naicsTitle ? "/NAICS scope" : ""} (${rfiQ.rows.length} found) ---`);
    if (rfiQ.rows.length === 0) {
      parts.push("None found in the current data for this SOC/NAICS scope.");
    } else {
      rfiQ.rows.forEach((r, i) => {
        parts.push(`[RFI ${i + 1}] (case ${r.case_number}): ${truncate(r.job_duties, MAX_DUTY_TEXT_CHARS * 2)}`);
      });
    }

    parts.push(`\n--- O*NET official reference for ${soc} ---`);
    parts.push(onetText || "No bundled O*NET reference file found for this SOC code.");

    parts.push(`\n--- Related occupations with BOTH O*NET data AND real Aztec filing/wage data (confirmed-risk tier) ---`);
    if (relatedWageRows.length === 0) {
      parts.push("None of this SOC's O*NET-related occupations are in Aztec's 26-code target dataset with wage data available.");
    } else {
      relatedWageRows.forEach((r) => {
        parts.push(`${r.soc_code} ${r.soc_title}: ${r.n} filings with wage data, average wage_from ${r.avg_wage}`);
      });
    }

    parts.push(`\n--- Related occupations with O*NET reference data only (general-awareness tier, no real filing data) ---`);
    if (relatedWithOnetFile.length === 0) {
      parts.push("None.");
    } else {
      relatedWithOnetFile.forEach((r) => {
        const text = loadOnetFile(r.soc_code);
        parts.push(`${r.soc_code} ${r.title}:\n${text}`);
      });
    }

    parts.push(`\n--- Related occupations with NEITHER real filing data NOR a bundled O*NET file (flag as needing a live lookup) ---`);
    if (relatedNoData.length === 0) {
      parts.push("None.");
    } else {
      relatedNoData.forEach((r) => parts.push(`${r.soc_code} ${r.title}`));
    }

    const userMessage = parts.join("\n");

    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) {
      return res.status(500).json({ error: "ANTHROPIC_API_KEY is not set in this environment's variables." });
    }
    const client = new Anthropic({ apiKey });
    // Claude Sonnet 5 defaults to adaptive thinking at effort: "high" whenever
    // output_config isn't specified, which was silently eating the entire
    // max_tokens budget on internal reasoning and leaving nothing for the
    // actual answer text (stop_reason: "max_tokens", only a "thinking" block
    // returned). "medium" keeps some of that reasoning quality for this fairly
    // structured task while leaving reliable headroom for the answer itself.
    const msg = await client.messages.create({
      model: MODEL,
      max_tokens: Number(process.env.MAX_OUTPUT_TOKENS || 8000),
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: userMessage }],
      output_config: { effort: process.env.MODEL_EFFORT || "medium" },
    });

    // Diagnostic logging (visible in Vercel's function logs), cheap to leave
    // in during the beta: tells us the stop reason and what block types came
    // back, which is the fastest way to see why an output might be empty.
    console.log(
      "generate-duties: stop_reason=%s content_block_types=%s usage=%s",
      msg.stop_reason,
      JSON.stringify((msg.content || []).map((c) => c.type)),
      JSON.stringify(msg.usage)
    );

    const outputText = msg.content.map((c) => (c.type === "text" ? c.text : "")).join("");

    if (!outputText.trim()) {
      return res.status(502).json({
        error: `Model returned no text content (stop_reason: ${msg.stop_reason}, block types: ${(msg.content || []).map((c) => c.type).join(", ") || "none"}). This usually means the response was cut off before any answer text was produced; try again, and if it keeps happening the max_tokens budget likely needs to be raised.`,
      });
    }

    return res.status(200).json({ output: outputText });
  } catch (err) {
    return res.status(500).json({ error: String(err.message || err) });
  }
};
