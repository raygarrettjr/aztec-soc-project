const { Pool } = require("pg");

let _pool = null;
function getPool() {
  if (!_pool) {
    const connectionString = process.env.SUPABASE_DB_URL;
    if (!connectionString) {
      throw new Error("SUPABASE_DB_URL is not set in this environment's variables.");
    }
    _pool = new Pool({ connectionString, ssl: { rejectUnauthorized: false }, max: 3 });
  }
  return _pool;
}

module.exports = { getPool };
