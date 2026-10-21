/* docs/guides/guide.js — the guides' contents (from the h2 headings into <nav class="toc">) and a picture opened large on a click. */
(() => {
  const toc = document.querySelector('.toc ol');
  if (toc) for (const h of document.querySelectorAll('main h2[id]')) {
    const li = document.createElement('li'), a = document.createElement('a');
    a.href = '#' + h.id; a.textContent = h.textContent; li.append(a); toc.append(li);
  }
  for (const img of document.querySelectorAll('figure img')) {
    img.classList.add('w');
    img.addEventListener('click', () => {
      const z = document.createElement('div'), big = new Image();
      z.className = 'zoom'; big.src = img.src; big.alt = img.alt; z.append(big);
      const close = () => { z.remove(); removeEventListener('keydown', esc); }, esc = e => { if (e.key === 'Escape') close(); };
      z.addEventListener('click', close); addEventListener('keydown', esc); document.body.append(z);
    });
  }
})();
