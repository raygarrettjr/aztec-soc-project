const { getPool } = require("./lib/db");
const { resolveNaicsTitle, loadTargetSocs } = require("./lib/reference");

exports.handler = async (event) => {
  try {
    const soc = (event.queryStringParameters && event.queryStringParameters.soc) || "";
    const targetSocs = loadTargetSocs();
    if (!targetSocs.some((s) => s.soc_code === soc)) {
      return { statusCode: 400, body: JSON.stringify({ error: "Unknown or missing SOC code." }) };
    }

    const pool = getPool();
    const { rows } = await pool.query(
      `SELECT naics_code, count(*) AS n
       FROM h2b_cases
       WHERE soc_code = $1 AND naics_code IS NOT NULL AND naics_code != ''
       GROUP BY naics_code
       ORDER BY n DESC`,
      [soc]
    );

    // Group raw naics_code values (which appear at varying digit precision)
    // by resolved title, so the dropdown shows one clean industry description
    // per group rather than every raw code variant.
    const byTitle = new Map(); // title -> { title, codes: [], count }
    const unresolved = [];
    for (const row of rows) {
      const title = resolveNaicsTitle(row.naics_code);
      const n = Number(row.n);
      if (!title) {
        unresolved.push({ naics_code: row.naics_code, count: n });
        continue;
      }
      if (!byTitle.has(title)) byTitle.set(title, { title, codes: [], count: 0 });
      const entry = byTitle.get(title);
      entry.codes.push(row.naics_code);
      entry.count += n;
    }

    const options = Array.from(byTitle.values()).sort((a, b) => b.count - a.count);

    return {
      statusCode: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ options, unresolved }),
    };
  } catch (err) {
    return { statusCode: 500, body: JSON.stringify({ error: String(err.message || err) }) };
  }
};
