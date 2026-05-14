function setupHeader() {
    const nav = document.querySelector('header nav');
    if (!nav) return;

    const links = nav.querySelectorAll('a');
    links.forEach(link => {
        if (!link.dataset.inited) {
            link.addEventListener('click', () => {
                nav.classList.remove('active');
            });
            link.dataset.inited = '1';
        }
    });

    if (!document.body.dataset.headerOutsideClick) {
        document.addEventListener('click', (e) => {
            if (!nav.contains(e.target)) {
                nav.classList.remove('active');
            }
        });
        document.body.dataset.headerOutsideClick = '1';
    }

    // Highlight active link by pathname
    const currentPath = window.location.pathname.replace(/\/+$/, '') || '/';
    const linksArr = Array.from(links);
    linksArr.forEach(a => a.classList.remove('active'));
    const match = linksArr.find(a => {
        const hrefPath = new URL(a.href, window.location.origin).pathname.replace(/\/+$/, '');
        return hrefPath === currentPath;
    });
    if (match) {
        match.classList.add('active');
    } else if (currentPath === '/' || currentPath === '') {
        const monitoreo = linksArr.find(a => new URL(a.href, window.location.origin).pathname.replace(/\/+$/, '') === '/ccomercial.html');
        if (monitoreo) monitoreo.classList.add('active');
    }
}

// Expose for components.js to call after header is injected
window.setupHeader = setupHeader;

// Also try on DOMContentLoaded in case header is already present
document.addEventListener('DOMContentLoaded', setupHeader);