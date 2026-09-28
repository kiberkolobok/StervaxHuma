// Создаем элемент canvas динамически, чтобы не засорять HTML
const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');
document.querySelector('.container').appendChild(canvas);

// Подгоняем размер холста под экран
function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener('resize', resizeCanvas);

// Массив для хранения звезд
let stars = [];
const starCount = 350; // Общее количество звезд (работает идеально плавно)

// Инициализация звезд
for (let i = 0; i < starCount; i++) {
    stars.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        size: Math.random() * 2 + 0.5,             // Размер от 0.5 до 2.5 пикселей
        speed: Math.random() * 0.1 + 0.2,           // Скорость падения вниз
        alpha: Math.random(),                      // Текущая прозрачность
        alphaSpeed: (Math.random() * 0.000002 + 0.00005) // Скорость мерцания (у каждой своя!)
    });
}

// Главный цикл анимации (60 кадров в секунду)
function animate() {
    // Очищаем экран
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Рисуем и двигаем каждую звезду
    stars.forEach(star => {
        // Движение вниз
        star.y += star.speed;
        if (star.y > canvas.height) {
            star.y = 0; // Возвращаем наверх при выходе за экран
            star.x = Math.random() * canvas.width;
        }

        // Плавное мерцание (изменение альфа-канала туда-сюда)
        star.alpha += star.alphaSpeed;
        if (star.alpha <= 0.1 || star.alpha >= 1) {
            star.alphaSpeed = -star.alphaSpeed; // Меняем направление мерцания
        }

        // Рисуем звезду
        ctx.fillStyle = `rgba(255, 255, 255, ${star.alpha})`;
        ctx.beginPath();
        ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
        ctx.fill();
    });

    requestAnimationFrame(animate);
}

// Запуск анимации
animate();