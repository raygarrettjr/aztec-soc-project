const Anthropic = require("@anthropic-ai/sdk");
const { getPool } = require("./lib/db");
const { SYSTEM_PROMPT } = require("./lib/instructions");
const {
  loadOnetFile,
  parseRelatedOccupations,
  resolveNaicsTitle,
  loadTargetSocs,
} = require("./lib/reference");

const SAMPLE_SIZE = Number(process.env.DUTY_SAMPLE_SIZE || 300);
const RFI_SAMPLE_SIZE = Number(process.env.RFI_SAMPLE_SIZE || 12);
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-5";

exports.handler = async (event) => {
  try {
    if (event.httpMethod !== "POST") {
      return { statusCode: 405, body: JSON.stringify({ error: "Use POST." }) };
    }
    const body = JSON.parse(event.body || "{}");
    const soc = body.soc;
    const naicsCodes = Array.isArray(body.naicsCodes) && body.naicsCodes.length ? body.naicsCodes : null;

    const targetSocs = loadTargetSocs();
    const socEntry = targetSocs.find((s) => s.soc_code === soc);
    if (!socEntry) {
      return { statusCode: 400, body: JSON.stringify({ error: "Unknown or missing SOC code." }) };
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

    parts.push(`\n--- Sample of ${sampleQ.rows.length} real job_duties entries for this SOC${naicsTitle ? "/NAICS scope" : ""} (use this to estimate duty and tool phrase frequency) ---`);
    sampleQ.rows.forEach((r, i) => {
      parts.push(`[${i + 1}] (case ${r.case_number}): ${r.job_duties}`);
    });

    parts.push(`\n--- RFI-flagged snippets found for this SOC${naicsTitle ? "/NAICS scope" : ""} (${rfiQ.rows.length} found) ---`);
    if (rfiQ.rows.length === 0) {
      parts.push("None found in the current data for this SOC/NAICS scope.");
    } else {
      rfiQ.rows.forEach((r, i) => {
        parts.push(`[RFI ${i + 1}] (case ${r.case_number}): ${r.job_duties}`);
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
      return { statusCode: 500, body: JSON.stringify({ error: "ANTHROPIC_API_KEY is not set in this environment's variables." }) };
    }
    const client = new Anthropic({ apiKey });
    const msg = await client.messages.create({
      model: MODEL,
      max_tokens: 4000,
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: userMessage }],
    });

    const outputText = msg.content.map((c) => (c.type === "text" ? c.text : "")).join("");

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output: outputText }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: String(err.message || err) }) };
  }
};
