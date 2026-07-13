const socSelect = document.getElementById('soc-select');
const naicsSelect = document.getElementById('naics-select');
const generateBtn = document.getElementById('generate-btn');
const statusEl = document.getElementById('status');
const errorEl = document.getElementById('error');
const outputCard = document.getElementById('output-card');
const outputEl = document.getElementById('output');
const copyBtn = document.getElementById('copy-btn');

const TARGET_SOCS = [
  { soc_code: "35-1012.00", soc_title: "First-Line Supervisors of Food Preparation and Serving Workers" },
  { soc_code: "35-2011.00", soc_title: "Cooks, Fast Food" },
  { soc_code: "35-2014.00", soc_title: "Cooks, Restaurant" },
  { soc_code: "35-2015.00", soc_title: "Cooks, Short Order" },
  { soc_code: "35-2021.00", soc_title: "Food Preparation Workers" },
  { soc_code: "35-3011.00", soc_title: "Bartenders" },
  { soc_code: "35-3023.00", soc_title: "Fast Food and Counter Workers" },
  { soc_code: "35-3031.00", soc_title: "Waiters and Waitresses" },
  { soc_code: "35-9011.00", soc_title: "Dining Room and Cafeteria Attendants and Bartender Helpers" },
  { soc_code: "35-9021.00", soc_title: "Dishwashers" },
  { soc_code: "37-2011.00", soc_title: "Janitors and Cleaners, Except Maids and Housekeeping Cleaners" },
  { soc_code: "37-2012.00", soc_title: "Maids and Housekeeping Cleaners" },
  { soc_code: "37-3011.00", soc_title: "Landscaping and Groundskeeping Workers" },
  { soc_code: "37-3012.00", soc_title: "Pesticide Handlers, Sprayers, and Applicators, Vegetation" },
  { soc_code: "39-2021.00", soc_title: "Animal Caretakers" },
  { soc_code: "39-3091.00", soc_title: "Amusement and Recreation Attendants" },
  { soc_code: "43-4081.00", soc_title: "Hotel, Motel, and Resort Desk Clerks" },
  { soc_code: "45-4011.00", soc_title: "Forest and Conservation Workers" },
  { soc_code: "47-2051.00", soc_title: "Cement Masons and Concrete Finishers" },
  { soc_code: "47-2061.00", soc_title: "Construction Laborers" },
  { soc_code: "47-3016.00", soc_title: "Helpers--Roofers" },
  { soc_code: "49-9098.00", soc_title: "Helpers--Installation, Maintenance, and Repair Workers" },
  { soc_code: "51-3022.00", soc_title: "Meat, Poultry, and Fish Cutters and Trimmers" },
  { soc_code: "53-3032.00", soc_title: "Heavy and Tractor-Trailer Truck Drivers" },
  { soc_code: "53-7062.00", soc_title: "Laborers and Freight, Stock, and Material Movers, Hand" },
  { soc_code: "53-7064.00", soc_title: "Packers and Packagers, Hand" }
];

TARGET_SOCS.sort((a, b) => a.soc_title.localeCompare(b.soc_title)).forEach(s => {
  const opt = document.createElement('option');
  opt.value = s.soc_code;
  opt.textContent = `${s.soc_title} (${s.soc_code})`;
  socSelect.appendChild(opt);
});

// Visible, no-DevTools-required confirmation that this script actually ran,
// since we've been burned before by scripts silently failing to execute.
statusEl.textContent = `Loaded ${TARGET_SOCS.length} occupations. Ready.`;

socSelect.addEventListener('change', async () => {
  const soc = socSelect.value;
  naicsSelect.innerHTML = '';
  naicsSelect.disabled = true;
  generateBtn.disabled = true;
  errorEl.textContent = '';

  if (!soc) {
    naicsSelect.innerHTML = '<option value="">Select an occupation first...</option>';
    return;
  }

  naicsSelect.innerHTML = '<option value="">Loading industry options...</option>';
  try {
    const res = await fetch(`/api/naics-options?soc=${encodeURIComponent(soc)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load industry options.');

    naicsSelect.innerHTML = '';
    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All industries (no NAICS filter)';
    naicsSelect.appendChild(allOpt);

    (data.options || []).forEach(o => {
      const opt = document.createElement('option');
      opt.value = JSON.stringify(o.codes);
      opt.textContent = `${o.title} (${o.count} filings)`;
      naicsSelect.appendChild(opt);
    });

    naicsSelect.disabled = false;
    generateBtn.disabled = false;
  } catch (err) {
    errorEl.textContent = 'Could not load industry options: ' + err.message;
    naicsSelect.innerHTML = '<option value="">All industries (no NAICS filter)</option>';
    naicsSelect.disabled = false;
    generateBtn.disabled = false;
  }
});

generateBtn.addEventListener('click', async () => {
  const soc = socSelect.value;
  if (!soc) return;
  const naicsVal = naicsSelect.value;
  const naicsCodes = naicsVal ? JSON.parse(naicsVal) : null;

  generateBtn.disabled = true;
  outputCard.style.display = 'none';
  errorEl.textContent = '';
  statusEl.textContent = 'Pulling live filing data and generating suggestion... this can take 20-40 seconds.';

  try {
    const res = await fetch('/api/generate-duties', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ soc, naicsCodes }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Generation failed.');

    console.log('generate-duties response length:', (data.output || '').length);
    console.log('generate-duties response preview:', (data.output || '').slice(0, 200));

    if (!data.output || !data.output.trim()) {
      errorEl.textContent = 'Error: server returned an empty response body (see Console tab for details).';
      statusEl.textContent = '';
      return;
    }

    let rendered;
    try {
      rendered = marked.parse(data.output);
    } catch (parseErr) {
      console.error('marked.parse failed:', parseErr);
      rendered = null;
    }

    if (rendered && rendered.trim()) {
      outputEl.innerHTML = rendered;
    } else {
      // Fallback: if the Markdown renderer fails for any reason, show the
      // raw text rather than nothing, so the user never sees a blank card.
      outputEl.textContent = data.output;
    }
    outputCard.style.display = 'block';
    statusEl.textContent = '';
  } catch (err) {
    errorEl.textContent = 'Error: ' + err.message;
    statusEl.textContent = '';
  } finally {
    generateBtn.disabled = false;
  }
});

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(outputEl.innerText).then(() => {
    copyBtn.textContent = 'Copied!';
    setTimeout(() => (copyBtn.textContent = 'Copy to clipboard'), 1500);
  });
});
