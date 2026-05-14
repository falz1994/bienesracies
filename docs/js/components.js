document.addEventListener('DOMContentLoaded', function() {
    // Cargar el header
    const headerComponent = document.getElementById('header-component');
    if (headerComponent) {
        fetch('/components/header.html')
            .then(response => response.text())
            .then(data => {
                headerComponent.innerHTML = data;
                if (window.setupHeader) {
                    window.setupHeader();
                }
            })
            .catch(error => console.error('Error cargando el header:', error));
    }

    // Cargar el footer
    const footerComponent = document.getElementById('footer-component');
    if (footerComponent) {
        fetch('/components/footer.html')
            .then(response => response.text())
            .then(data => {
                footerComponent.innerHTML = data;
            })
            .catch(error => console.error('Error cargando el footer:', error));
    }
});

