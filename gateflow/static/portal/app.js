const apiKeyInput = document.getElementById('api-key');
const loadBtn = document.getElementById('load-btn');
const quotaCard = document.getElementById('quota-card');
const actionsCard = document.getElementById('actions-card');
const quotaDl = document.getElementById('quota-dl');
const rotateBtn = document.getElementById('rotate-btn');
const tierForm = document.getElementById('tier-form');
const result = document.getElementById('result');

function setResult(message, isError = false) {
  result.textContent = message;
  result.style.color = isError ? '#dc2626' : 'var(--muted)';
}

async function withKey() {
  const key = apiKeyInput.value.trim();
  if (!key) {
    setResult('Please enter an API key.', true);
    return null;
  }
  return key;
}

async function loadQuota() {
  const key = await withKey();
  if (!key) return;
  try {
    const res = await fetch('/api/me/quota', {
      headers: { 'X-API-KEY': key },
    });
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    quotaDl.innerHTML = Object.entries(data)
      .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
      .join('');
    quotaCard.classList.remove('hidden');
    actionsCard.classList.remove('hidden');
    setResult('');
  } catch (err) {
    setResult(`Failed to load quota: ${err.message}`, true);
  }
}

async function rotateKey() {
  const key = await withKey();
  if (!key) return;
  try {
    const res = await fetch('/api/me/keys/rotate', {
      method: 'POST',
      headers: { 'X-API-KEY': key },
    });
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    apiKeyInput.value = data.api_key;
    setResult(`Key rotated. New key has been inserted in the API Key field.`);
  } catch (err) {
    setResult(`Failed to rotate key: ${err.message}`, true);
  }
}

async function requestTier(event) {
  event.preventDefault();
  const key = await withKey();
  if (!key) return;
  const tier = document.getElementById('tier').value.trim();
  const reasonText = document.getElementById('reason').value.trim();
  const params = new URLSearchParams({ requested_tier: tier, reason: reasonText });
  try {
    const res = await fetch(`/api/me/tier/request?${params}`, {
      method: 'POST',
      headers: { 'X-API-KEY': key },
    });
    if (!res.ok) throw new Error(res.statusText);
    setResult('Tier change request submitted.');
  } catch (err) {
    setResult(`Failed to request tier: ${err.message}`, true);
  }
}

loadBtn.addEventListener('click', loadQuota);
rotateBtn.addEventListener('click', rotateKey);
tierForm.addEventListener('submit', requestTier);
