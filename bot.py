import logging
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# Загрузка переменных окружения из файла .env
load_dotenv()
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Токен бота не найден в файле .env!")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# ID администратора и кухни
ADMIN_ID = 5333876903
KITCHEN_ID = 5333876903

# Главное меню
menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍔 Меню"), KeyboardButton(text="🛒 Корзина")],
        [KeyboardButton(text="📞 Контакты"), KeyboardButton(text="ℹ️ О нас")]
    ],
    resize_keyboard=True
)

# Меню с товарами
menu_items = {
    "Суши": {
        "Суши с лососем": {"price": 600, "description": "Свежий лосось, рис, нори.", "photo": "images/sushi_salmon.jpg"},
        "Суши с тунцом": {"price": 650, "description": "Нежный тунец с остринкой.", "photo": "images/sushi_tuna.jpg"}
    },
    "Бургеры": {
        "Бургер с говядиной": {"price": 350, "description": "Сочная говядина, овощи, соус.", "photo": "images/beef_burger.jpg"},
        "Бургер с курицей": {"price": 320, "description": "Хрустящая курица и майонез.", "photo": "images/chicken_burger.jpg"},
        "Фирменные картофельные дольки": {"price": 250, "description": "Золотистые дольки со специями.", "photo": "images/potato_wedges.jpg"}
    },
    "Пицца": {
        "Пицца Маргарита": {"price": 450, "description": "Томаты, моцарелла, базилик.", "photo": "images/margherita.jpg"},
        "Пицца Пепперони": {"price": 500, "description": "Острая пепперони и сыр.", "photo": "images/pepperoni.jpg"}
    },
    "Холодные блюда": {
        "Греческий салат": {"price": 350, "description": "Оливки, фета, огурцы.", "photo": "images/greek_salad.jpg"},
        "Цезарь с курицей": {"price": 400, "description": "Курица, сухарики, пармезан.", "photo": "images/caesar.jpg"}
    },
    "Напитки": {
        "Напиток Coca-Cola 0.5л": {"price": 150, "description": "Освежающая кола.", "photo": "images/coca_cola.jpg"}
    }
}

# Константы и структуры данных
ITEMS_PER_PAGE = 3
user_carts = {}

# Функции для работы с заказами в JSON
def load_orders():
    try:
        with open("orders.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_orders(orders_dict):
    with open("orders.json", "w") as f:
        json.dump(orders_dict, f)

orders = load_orders()

# Состояния для оформления заказа
class Order(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    confirm_data = State()

# Состояния для редактирования заказа
class EditOrder(StatesGroup):
    select_field = State()
    edit_name = State()
    edit_phone = State()
    edit_address = State()
    edit_cart = State()
    confirm_edit = State()

# Работа с Google Sheets
def get_google_sheet():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name('google_credentials.json', scope)
        client = gspread.authorize(creds)
        sheet = client.open('FoodDeliveryCustomers').sheet1
        return sheet
    except Exception as e:
        print(f"Ошибка при подключении к Google Sheets: {e}")
        return None

def find_order_in_sheet(phone):
    sheet = get_google_sheet()
    if not sheet:
        return None
    all_records = sheet.get_all_values()
    for i, row in enumerate(all_records, start=1):
        if len(row) > 1 and row[1] == phone:
            return i
    return None

async def update_or_add_order_to_sheet(order_data):
    try:
        sheet = get_google_sheet()
        if not sheet:
            await bot.send_message(ADMIN_ID, "⚠️ Не удалось подключиться к Google Sheets!")
            return
        phone = order_data[1]
        row_index = find_order_in_sheet(phone)
        if row_index:
            sheet.update(f"A{row_index}:E{row_index}", [order_data])
            print(f"Заказ с телефоном {phone} обновлен в Google Sheets!")
        else:
            sheet.append_row(order_data)
            print(f"Новый заказ с телефоном {phone} добавлен в Google Sheets!")
    except Exception as e:
        await bot.send_message(ADMIN_ID, f"⚠️ Ошибка при работе с Google Sheets: {e}")
        print(f"Ошибка: {e}")

# Расчет общей стоимости корзины
def calculate_total_price(cart):
    return sum(menu_items[cat][item]["price"] for cat in menu_items for item in cart if item in menu_items[cat])

# Уведомления администратора и кухни
async def notify_admin(order_data, phone, username):
    try:
        message = (
            f"📦 *Новый заказ!*\n\n"
            f"👤 Имя: {order_data[0]}\n"
            f"📞 Телефон: {order_data[1]}\n"
            f"🏠 Адрес: {order_data[2]}\n"
            f"🛒 Заказ: {order_data[3]}\n"
            f"💰 Сумма: {order_data[4]}₽\n\n"
            f"👤 Username: @{username}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data=f"confirm_{phone}")],
            [InlineKeyboardButton(text="✏️ Редактировать заказ", callback_data=f"edit_{phone}")],
            [InlineKeyboardButton(text="📞 Связаться с клиентом", callback_data=f"contact_{phone}")]
        ])
        await bot.send_message(ADMIN_ID, message, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка уведомления администратора: {e}")

async def notify_kitchen(order_data, username):
    try:
        message = (
            f"🔥 *Заказ на кухню!*\n\n"
            f"👤 Имя: {order_data[0]}\n"
            f"📞 Телефон: {order_data[1]}\n"
            f"🏠 Адрес: {order_data[2]}\n"
            f"🛒 Заказ: {order_data[3]}\n"
            f"💰 Сумма: {order_data[4]}₽\n\n"
            f"👤 Username: @{username}"
        )
        await bot.send_message(KITCHEN_ID, message, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка уведомления кухни: {e}")

# Обработчики команд и сообщений
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Добро пожаловать в сервис доставки еды! 🛵🍔", reply_markup=menu_keyboard)

@dp.message(lambda message: message.text == "🍔 Меню")
async def show_menu_categories(message: types.Message, state: FSMContext):
    await state.set_state(None)
    categories = list(menu_items.keys())
    await show_categories_page(message, state, 0)

# Пагинация категорий
async def show_categories_page(message: types.Message, state: FSMContext, page: int):
    categories = list(menu_items.keys())
    start_index = page * ITEMS_PER_PAGE
    end_index = min((page + 1) * ITEMS_PER_PAGE, len(categories))
    current_categories = categories[start_index:end_index]

    keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
        [InlineKeyboardButton(text=category, callback_data=f"category_{category}")]
        for category in current_categories
    ])

    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"categories_page_{page - 1}"))
    if end_index < len(categories):
        navigation_buttons.append(
            InlineKeyboardButton(text="➡️ Далее", callback_data=f"categories_page_{page + 1}"))
    if navigation_buttons:
        keyboard.inline_keyboard.append(navigation_buttons)

    await message.answer("Выберите категорию:", reply_markup=keyboard)

@dp.callback_query(lambda callback: callback.data.startswith("categories_page_"))
async def navigate_categories(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data[16:])
    await show_categories_page(callback.message, state, page)
    await callback.answer()

# Пагинация товаров в категории
@dp.callback_query(lambda callback: callback.data.startswith("category_"))
async def show_menu_items(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data[9:]
    await state.set_state(None)
    await show_items_page(callback.message, state, category, 0)

async def show_items_page(message: types.Message, state: FSMContext, category: str, page: int):
    items = list(menu_items[category].items())
    start_index = page * ITEMS_PER_PAGE
    end_index = min((page + 1) * ITEMS_PER_PAGE, len(items))
    current_items = items[start_index:end_index]

    keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[
        [InlineKeyboardButton(text=item, callback_data=f"item_{item}")]
        for item, _ in current_items
    ])

    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"items_page_{category}_{page - 1}"))
    if end_index < len(items):
        navigation_buttons.append(
            InlineKeyboardButton(text="➡️ Далее", callback_data=f"items_page_{category}_{page + 1}"))
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="⬅️ К категориям", callback_data="back_to_categories")])
    if navigation_buttons:
        keyboard.inline_keyboard.append(navigation_buttons)

    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(f"*{category}:*", parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.answer(f"*{category}:*", parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(lambda callback: callback.data.startswith("items_page_"))
async def navigate_items(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data[11:].split("_")
    category = data[0]
    page = int(data[-1])
    await show_items_page(callback.message, state, category, page)
    await callback.answer()

@dp.callback_query(lambda callback: callback.data == "back_to_categories")
async def back_to_categories(callback: types.CallbackQuery, state: FSMContext):
    await show_menu_categories(callback.message, state)
    await callback.answer()

# Карточка товара
@dp.callback_query(lambda callback: callback.data.startswith("item_"))
async def show_item_card(callback: types.CallbackQuery):
    item_name = callback.data[5:]
    category = next((cat for cat, items in menu_items.items() if item_name in items), None)
    if not category:
        await callback.answer("Ошибка: Товар не найден!", show_alert=True)
        return

    item = menu_items[category][item_name]
    caption = (
        f"*{item_name}*\n\n"
        f"📝 {item['description']}\n"
        f"💰 Цена: {item['price']}₽"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить в корзину", callback_data=f"add_{item_name}")],
        [InlineKeyboardButton(text="⬅️ Назад к меню", callback_data=f"category_{category}")]
    ])

    try:
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=FSInputFile(item["photo"]),
            caption=caption,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except FileNotFoundError:
        await callback.answer("Ошибка: Фото товара не найдено!", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

    await callback.answer()

# Добавление в корзину
@dp.callback_query(lambda callback: callback.data.startswith("add_"))
async def add_to_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    item_name = callback.data[4:]
    category = next((cat for cat, items in menu_items.items() if item_name in items), None)
    if not category:
        await callback.answer("Ошибка: Товар не найден!", show_alert=True)
        return

    if user_id not in user_carts:
        user_carts[user_id] = []
    user_carts[user_id].append(item_name)
    await callback.answer(f"{item_name} добавлен в корзину! ✅", show_alert=False)

# Просмотр корзины
@dp.message(lambda message: message.text == "🛒 Корзина")
async def view_cart(message: types.Message):
    user_id = message.from_user.id
    cart = user_carts.get(user_id, [])

    if not cart:
        await message.answer("🛒 Ваша корзина пуста.", reply_markup=menu_keyboard)
        return

    cart_summary = "\n".join(cart)
    total_price = calculate_total_price(cart)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton(text="❌ Очистить корзину", callback_data="clear_cart")]
    ])

    await message.answer(f"🛒 *Ваша корзина:*\n{cart_summary}\n\n💰 *Общая сумма:* {total_price}₽",
                         parse_mode="Markdown", reply_markup=keyboard)

# Очистка корзины
@dp.callback_query(lambda callback: callback.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_carts[user_id] = []
    await callback.answer("🛒 Корзина очищена!", show_alert=True)
    await callback.message.edit_text("🛒 Ваша корзина пуста.", reply_markup=menu_keyboard)

# Оформление заказа
@dp.callback_query(lambda callback: callback.data == "checkout")
async def checkout(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username
    cart = user_carts.get(user_id, [])

    if not cart:
        await callback.answer("🛒 Ваша корзина пуста!", show_alert=True)
        return

    await state.update_data(cart=cart, total_price=calculate_total_price(cart), username=username)
    await state.set_state(Order.waiting_for_name)
    await callback.message.answer("Пожалуйста, введите ваше ФИО:")

@dp.message(Order.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(Order.waiting_for_phone)
    await message.answer("Теперь введите ваш номер телефона:")

@dp.message(Order.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await state.set_state(Order.waiting_for_address)
    await message.answer("Теперь введите ваш адрес доставки:")

@dp.message(Order.waiting_for_address)
async def process_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    await state.set_state(Order.confirm_data)

    user_data = await state.get_data()
    cart_summary = "\n".join(user_data["cart"])
    total_price = user_data["total_price"]

    confirm_message = (
        f"📦 *Ваш заказ:*\n\n"
        f"👤 ФИО: {user_data['name']}\n"
        f"📞 Телефон: {user_data['phone']}\n"
        f"🏠 Адрес: {user_data['address']}\n"
        f"🛒 Заказ:\n{cart_summary}\n"
        f"💰 Итого: {total_price}₽\n\n"
        f"Всё верно?"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, всё верно", callback_data="confirm_order")],
        [InlineKeyboardButton(text="❌ Нет, изменить данные", callback_data="cancel_order")]
    ])

    await message.answer(confirm_message, parse_mode="Markdown", reply_markup=keyboard)

# Подтверждение заказа клиентом
@dp.callback_query(lambda callback: callback.data == "confirm_order")
async def confirm_order(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()

    order_data = {
        "name": user_data["name"],
        "phone": user_data["phone"],
        "address": user_data["address"],
        "cart": user_data["cart"],
        "total_price": user_data["total_price"],
        "username": user_data.get("username", "")
    }

    orders[user_data["phone"]] = order_data
    save_orders(orders)

    await notify_admin([
        order_data["name"],
        order_data["phone"],
        order_data["address"],
        "\n".join(order_data["cart"]),
        order_data["total_price"]
    ], order_data["phone"], order_data["username"])

    user_id = callback.from_user.id
    user_carts.pop(user_id, [])
    await callback.message.answer("✅ Заказ оформлен! Ожидайте подтверждения администратора. 🚀", reply_markup=menu_keyboard)
    await state.clear()

# Отмена заказа клиентом
@dp.callback_query(lambda callback: callback.data == "cancel_order")
async def cancel_order(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Заказ отменён. Вы можете начать заново.", reply_markup=menu_keyboard)

# Связь с клиентом
@dp.callback_query(lambda callback: callback.data.startswith("contact_"))
async def contact_client(callback: types.CallbackQuery):
    phone = callback.data.split("_")[1]
    await callback.answer(f"Позвоните клиенту по номеру: {phone}", show_alert=True)

# Редактирование заказа администратором
async def show_edit_options(message: types.Message, phone: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 ФИО", callback_data=f"edit_name_{phone}")],
        [InlineKeyboardButton(text="📞 Телефон", callback_data=f"edit_phone_{phone}")],
        [InlineKeyboardButton(text="🏠 Адрес", callback_data=f"edit_address_{phone}")],
        [InlineKeyboardButton(text="🛒 Состав заказа", callback_data=f"edit_cart_{phone}")],
        [InlineKeyboardButton(text="✅ Подтвердить изменения", callback_data=f"confirm_edit_{phone}")]
    ])
    await message.answer("Выберите, что хотите отредактировать:", reply_markup=keyboard)

@dp.callback_query(lambda callback: callback.data.startswith("edit_") and "name" not in callback.data and "phone" not in callback.data and "address" not in callback.data and "cart" not in callback.data and "confirm" not in callback.data)
async def start_edit_order(callback: types.CallbackQuery, state: FSMContext):
    phone = callback.data.split("_")[1]
    await state.update_data(phone=phone)
    await show_edit_options(callback.message, phone)
    await callback.answer()

@dp.callback_query(lambda callback: callback.data.startswith("edit_name_"))
async def edit_name(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditOrder.edit_name)
    await callback.message.answer("Введите новое ФИО:")

@dp.callback_query(lambda callback: callback.data.startswith("edit_phone_"))
async def edit_phone(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditOrder.edit_phone)
    await callback.message.answer("Введите новый номер телефона:")

@dp.callback_query(lambda callback: callback.data.startswith("edit_address_"))
async def edit_address(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditOrder.edit_address)
    await callback.message.answer("Введите новый адрес:")

@dp.callback_query(lambda callback: callback.data.startswith("edit_cart_"))
async def edit_cart(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EditOrder.edit_cart)
    await callback.message.answer("Введите новый состав заказа (каждый пункт с новой строки):")

@dp.message(EditOrder.edit_name)
async def process_edit_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    user_data = await state.get_data()
    await show_edit_options(message, user_data["phone"])

@dp.message(EditOrder.edit_phone)
async def process_edit_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    user_data = await state.get_data()
    await show_edit_options(message, user_data["phone"])

@dp.message(EditOrder.edit_address)
async def process_edit_address(message: types.Message, state: FSMContext):
    await state.update_data(address=message.text)
    user_data = await state.get_data()
    await show_edit_options(message, user_data["phone"])

@dp.message(EditOrder.edit_cart)
async def process_edit_cart(message: types.Message, state: FSMContext):
    cart = message.text.split("\n")
    await state.update_data(cart=cart)
    user_data = await state.get_data()
    await show_edit_options(message, user_data["phone"])

@dp.callback_query(lambda callback: callback.data.startswith("confirm_edit_"))
async def confirm_edit(callback: types.CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    phone = user_data["phone"]
    order_data = orders.get(phone, {})
    order_data.update({
        "name": user_data.get("name", order_data.get("name", "")),
        "phone": user_data.get("phone", order_data.get("phone", "")),
        "address": user_data.get("address", order_data.get("address", "")),
        "cart": user_data.get("cart", order_data.get("cart", [])),
        "total_price": calculate_total_price(user_data.get("cart", order_data.get("cart", []))),
    })
    orders[phone] = order_data
    save_orders(orders)
    await notify_admin([
        order_data["name"],
        order_data["phone"],
        order_data["address"],
        "\n".join(order_data["cart"]),
        order_data["total_price"]
    ], order_data["phone"], order_data.get("username", ""))
    await callback.message.answer("✅ Заказ отредактирован!", reply_markup=menu_keyboard)
    await state.clear()

# Подтверждение заказа администратором
@dp.callback_query(lambda callback: callback.data.startswith("confirm_"))
async def admin_confirm_order(callback: types.CallbackQuery):
    phone = callback.data.split("_")[1]

    if phone in orders:
        order_data = orders[phone]
        username = order_data.get("username", "")

        await notify_kitchen([
            order_data["name"],
            order_data["phone"],
            order_data["address"],
            "\n".join(order_data["cart"]),
            order_data["total_price"]
        ], username)

        await update_or_add_order_to_sheet([
            order_data["name"],
            order_data["phone"],
            order_data["address"],
            "\n".join(order_data["cart"]),
            str(order_data["total_price"])
        ])

        del orders[phone]
        save_orders(orders)

        await callback.answer("✅ Заказ подтверждён и отправлен на кухню!", show_alert=True)
    else:
        await callback.answer("❌ Заказ не найден!", show_alert=True)

# Дополнительные команды
@dp.message(lambda message: message.text == "📞 Контакты")
async def contacts(message: types.Message):
    await message.answer("📞 Наш телефон: +7 999 123 45 67\n🌍 Наш сайт: https://example.com", reply_markup=menu_keyboard)

@dp.message(lambda message: message.text == "ℹ️ О нас")
async def about_us(message: types.Message):
    await message.answer("🍔 Мы — лучшая доставка еды в городе! 🚀\nГотовим только из свежих продуктов!",
                         reply_markup=menu_keyboard)

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())