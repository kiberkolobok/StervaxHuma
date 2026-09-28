// Автоматически находим или создаем canvas для звездного неба
let canvas = document.querySelector('canvas');
if (!canvas) {
    canvas = document.createElement('canvas');
    document.body.prepend(canvas);
}

const ctx = canvas.getContext('2d');

let stars = [];
const numStars = 400; // Количество звезд

// Функция подгонки холста под текущий размер окна
function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}

// Инициализация звезд: все движутся строго вниз с разной скоростью (эффект глубины)
function initStars() {
    stars = [];
    for (let i = 0; i < numStars; i++) {
        stars.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            size: Math.random() * 1.8,
            // Скорость движения строго вниз (разная для создания объема)
            speedY: Math.random() * 0.06 + 0.2,
            alpha: Math.random(),
            twinkleSpeed: Math.random() * 0.0002 + 0.000005
        });
    }
}

// Анимация: движение вниз + мерцание
function animateStars() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    stars.forEach(star => {
        // Двигаем звезду строго вниз
        star.y += star.speedY;

        // Если звезда улетела за нижний край экрана, возвращаем ее на самый верх в случайную точку по X
        if (star.y > canvas.height) {
            star.y = 0;
            star.x = Math.random() * canvas.width;
        }

        // Эффект плавного мерцания прозрачности
        star.alpha += star.twinkleSpeed;
        if (star.alpha > 1 || star.alpha < 0.2) {
            star.twinkleSpeed = -star.twinkleSpeed;
        }

        // Рисуем звезду
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${star.alpha})`;
        ctx.fill();
    });

    requestAnimationFrame(animateStars);
}

// Первоначальный запуск
resizeCanvas();
initStars();
animateStars();

// Мгновенная адаптация при изменении размера окна браузера (без перезагрузки)
window.addEventListener('resize', () => {
    resizeCanvas();
    initStars(); // Пересоздаем звезды под новые размеры экрана
});
