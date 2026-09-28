// Список изображений. Добавляйте новые пути сюда, скрипт сгенерирует карточки автоматически.
const imagesList = [
    'images/art1.jpg',
    'images/art2.jpg',
    'images/art3.jpg',
    'images/art4.jpg',
    'images/art5.jpg'
];

const galleryTrack = document.getElementById('galleryTrack');

if (galleryTrack) {
    galleryTrack.innerHTML = '';

    imagesList.forEach((imgPath, index) => {
        const card = document.createElement('div');
        card.className = 'card';

        card.innerHTML = `
            <img src="${imgPath}" alt="Art ${index + 1}" class="card-img" onerror="this.parentElement.style.display='none'">
            <div class="card-overlay">Просмотр</div>
        `;

        // Клик для открытия превью в верхнем блоке
        card.addEventListener('click', () => {
            const bigImg = document.getElementById('big-preview-img');
            const container = document.querySelector('.container');
            if (bigImg && container) {
                bigImg.src = imgPath;
                container.classList.add('split-mode');
            }
        });

        galleryTrack.appendChild(card);
    });
}

// Прокрутка карусели
const trackContainer = document.getElementById('galleryContainer');
const btnLeft = document.getElementById('scrollLeft');
const btnRight = document.getElementById('scrollRight');

if (btnLeft && trackContainer) {
    btnLeft.addEventListener('click', () => {
        trackContainer.scrollBy({ left: -300, behavior: 'smooth' });
    });
}

if (btnRight && trackContainer) {
    btnRight.addEventListener('click', () => {
        trackContainer.scrollBy({ left: 300, behavior: 'smooth' });
    });
}

// Закрытие интерактивного окна
const closeBtn = document.querySelector('.close-view-btn');
if (closeBtn) {
    closeBtn.addEventListener('click', () => {
        const container = document.querySelector('.container');
        if (container) {
            container.classList.remove('split-mode');
        }
    });
}