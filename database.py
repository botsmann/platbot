import sqlite3
import os
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

DB_NAME = "restaurant_cleaner.db"


class Database:
    def __init__(self):
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(DB_NAME)

    def init_db(self):
        """Инициализация базы данных"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'executor',
                category TEXT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица задач
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY,
                created_by INTEGER,
                photo_before_id TEXT,
                photo_before_path TEXT,
                comment TEXT,
                status TEXT DEFAULT 'Новая',
                category TEXT,
                completed_by INTEGER,
                photo_after_id TEXT,
                photo_after_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(user_id),
                FOREIGN KEY (completed_by) REFERENCES users(user_id)
            )
        """)

        # Добавляем поле category в tasks, если его нет
        try:
            cursor.execute("ALTER TABLE tasks ADD COLUMN category TEXT")
        except sqlite3.OperationalError:
            pass  # Поле уже существует

        # Добавляем поле category в users, если его нет
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN category TEXT")
        except sqlite3.OperationalError:
            pass  # Поле уже существует
        
        # Добавляем поле last_active в users, если его нет
        try:
            # Проверяем, существует ли колонка
            cursor.execute("PRAGMA table_info(users)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'last_active' not in columns:
                # SQLite не позволяет добавлять колонку с DEFAULT CURRENT_TIMESTAMP
                # Добавляем колонку без DEFAULT, затем обновляем существующие записи
                cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP")
                cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE last_active IS NULL")
                conn.commit()
        except sqlite3.OperationalError as e:
            # Поле уже существует или другая ошибка
            pass

        conn.commit()
        conn.close()

    def _ensure_task_photos_table(self):
        """Вспомогательно: создать таблицу для нескольких фото, если ее нет"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                kind TEXT CHECK(kind IN ('before','after')) NOT NULL,
                file_id TEXT,
                file_path TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            )
        """)
        conn.commit()
        conn.close()

    def add_task_photo(self, task_id: int, kind: str, file_id: str, file_path: str):
        """Добавить фотографию к задаче (много фотографий)"""
        self._ensure_task_photos_table()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_photos (task_id, kind, file_id, file_path)
            VALUES (?, ?, ?, ?)
        """, (task_id, kind, file_id, file_path))
        conn.commit()
        conn.close()

    def get_task_photos(self, task_id: int) -> List[Dict]:
        """Получить список всех фотографий задачи"""
        self._ensure_task_photos_table()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, task_id, kind, file_id, file_path
            FROM task_photos WHERE task_id = ?
        """, (task_id,))
        rows = cursor.fetchall()
        conn.close()
        return [{'id': r[0], 'task_id': r[1], 'kind': r[2], 'file_id': r[3], 'file_path': r[4]} for r in rows]

    def delete_all_task_photos(self, task_id: int):
        """Удалить все фото задачи"""
        self._ensure_task_photos_table()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM task_photos WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()

    def get_user_role(self, user_id: int) -> str:
        """Получить роль пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else "executor"

    def get_username(self, user_id: int) -> Optional[str]:
        """Получить username пользователя по user_id"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def get_last_active(self, user_id: int) -> Optional[datetime]:
        """Получить время последней активности пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT last_active FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0]:
                try:
                    return datetime.fromisoformat(result[0])
                except ValueError:
                    return None
            return None
        except sqlite3.OperationalError as e:
            # Если колонки нет, добавляем её
            if "no such column: last_active" in str(e):
                try:
                    # SQLite не позволяет добавлять колонку с DEFAULT CURRENT_TIMESTAMP
                    # Добавляем колонку без DEFAULT, затем обновляем существующие записи
                    cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP")
                    cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE last_active IS NULL")
                    conn.commit()
                    conn.close()
                    # Повторяем запрос
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT last_active FROM users WHERE user_id = ?", (user_id,))
                    result = cursor.fetchone()
                    conn.close()
                    if result and result[0]:
                        try:
                            return datetime.fromisoformat(result[0])
                        except ValueError:
                            return None
                except Exception as ex:
                    logger.error(f"Ошибка при добавлении колонки last_active: {ex}")
                    conn.close()
                    return None
            else:
                conn.close()
                return None

    def set_user_role(self, user_id: int, username: str, role: str, category: Optional[str] = None):
        """Установить роль пользователя"""
        logger.debug(f"set_user_role вызван, user_id={user_id}, role={role}, category={category}")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if category:
                logger.debug("Выполняю INSERT OR REPLACE с категорией")
                cursor.execute("""
                    INSERT OR REPLACE INTO users (user_id, username, role, category, last_active)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, username, role, category))
            else:
                logger.debug("Выполняю INSERT OR REPLACE без категории")
                cursor.execute("""
                    INSERT OR REPLACE INTO users (user_id, username, role, last_active)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, username, role))
            conn.commit()
            logger.debug("Коммит выполнен")
            # Проверяем, что сохранилось
            cursor.execute("SELECT category FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            logger.debug(f"Проверка после set_user_role: category={result[0] if result else None}")
            conn.close()
        except sqlite3.OperationalError as e:
            logger.error(f"OperationalError в set_user_role: {e}")
            # Если колонки нет, добавляем её
            if "no such column: last_active" in str(e):
                try:
                    # SQLite не позволяет добавлять колонку с DEFAULT CURRENT_TIMESTAMP
                    # Добавляем колонку без DEFAULT, затем обновляем существующие записи
                    cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP")
                    cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE last_active IS NULL")
                    conn.commit()
                    # Теперь повторяем операцию
                    if category:
                        cursor.execute("""
                            INSERT OR REPLACE INTO users (user_id, username, role, category, last_active)
                            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, (user_id, username, role, category))
                    else:
                        cursor.execute("""
                            INSERT OR REPLACE INTO users (user_id, username, role, last_active)
                            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                        """, (user_id, username, role))
                    conn.commit()
                    logger.debug("Колонка last_active добавлена и данные обновлены")
                except Exception as ex:
                    logger.error(f"Исключение при обработке ошибки: {ex}", exc_info=True)
            conn.close()
        except Exception as e:
            logger.error(f"Общая ошибка в set_user_role: {e}", exc_info=True)
            conn.close()

    def set_user_category(self, user_id: int, username: str, category: str):
        """Установить категорию пользователя"""
        logger.debug(f"set_user_category вызван, user_id={user_id}, category={category}")
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # Пытаемся обновить только категорию, не затирая роль
            logger.debug(f"Выполняю UPDATE для user_id={user_id}")
            cursor.execute("UPDATE users SET username = ?, category = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (username, category, user_id))
            logger.debug(f"rowcount={cursor.rowcount}")
            if cursor.rowcount == 0:
                # Если пользователя нет, создаем как исполнителя по умолчанию
                logger.debug("Пользователь не найден, создаю нового")
                cursor.execute("INSERT INTO users (user_id, username, role, category, last_active) VALUES (?, ?, 'executor', ?, CURRENT_TIMESTAMP)", (user_id, username, category))
            conn.commit()
            logger.debug("Коммит выполнен в set_user_category")
            # Проверяем, что сохранилось
            cursor.execute("SELECT category FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            logger.debug(f"Проверка после set_user_category: category={result[0] if result else None}")
            conn.close()
        except sqlite3.OperationalError as e:
            logger.error(f"OperationalError в set_user_category: {e}")
            # Если колонки нет, добавляем её
            if "no such column: last_active" in str(e):
                try:
                    # SQLite не позволяет добавлять колонку с DEFAULT CURRENT_TIMESTAMP
                    # Добавляем колонку без DEFAULT, затем обновляем существующие записи
                    cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP")
                    cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE last_active IS NULL")
                    conn.commit()
                    # Теперь повторяем операцию
                    cursor.execute("UPDATE users SET username = ?, category = ?, last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (username, category, user_id))
                    if cursor.rowcount == 0:
                        cursor.execute("INSERT INTO users (user_id, username, role, category, last_active) VALUES (?, ?, 'executor', ?, CURRENT_TIMESTAMP)", (user_id, username, category))
                    conn.commit()
                    logger.debug("Колонка last_active добавлена и данные обновлены в set_user_category")
                except Exception as ex:
                    logger.error(f"Исключение при обработке ошибки в set_user_category: {ex}", exc_info=True)
            conn.close()
        except Exception as e:
            logger.error(f"Общая ошибка в set_user_category: {e}", exc_info=True)
            conn.close()

    def update_last_active(self, user_id: int):
        """Обновить время последней активности"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            # Если колонки нет, добавляем её
            if "no such column: last_active" in str(e):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                    conn.commit()
                    cursor.execute("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
                    conn.commit()
                except Exception:
                    pass
            conn.close()

    def mark_user_inactive(self, user_id: int):
        """Перевести пользователя в статус неактивного"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE users
                SET role = 'inactive',
                    category = NULL,
                    last_active = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            # Если колонки нет, добавляем её
            if "no such column: last_active" in str(e):
                try:
                    cursor.execute("ALTER TABLE users ADD COLUMN last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                    conn.commit()
                    cursor.execute("""
                        UPDATE users
                        SET role = 'inactive',
                            category = NULL,
                            last_active = CURRENT_TIMESTAMP
                        WHERE user_id = ?
                    """, (user_id,))
                    conn.commit()
                except Exception:
                    pass
            conn.close()

    def get_user_category(self, user_id: int) -> Optional[str]:
        """Получить категорию пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT category FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result and result[0] else None

    def get_users_by_category(self, category: str) -> List[Dict]:
        """Получить список пользователей по категории"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username FROM users WHERE category = ?", (category,))
        rows = cursor.fetchall()
        conn.close()
        return [{'user_id': row[0], 'username': row[1]} for row in rows]

    def create_task(self, created_by: int, photo_id: str, photo_path: str, comment: str, category: str) -> int:
        """Создать новую задачу с минимальным доступным ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Находим минимальный свободный ID
        cursor.execute("SELECT task_id FROM tasks ORDER BY task_id")
        existing_ids = {row[0] for row in cursor.fetchall()}
        
        # Ищем минимальный свободный ID
        task_id = 1
        while task_id in existing_ids:
            task_id += 1
        
        # Вставляем задачу с найденным ID
        cursor.execute("""
            INSERT INTO tasks (task_id, created_by, photo_before_id, photo_before_path, comment, status, category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (task_id, created_by, photo_id, photo_path, comment, "Новая", category))
        
        conn.commit()
        conn.close()
        return task_id

    def get_tasks(self, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict]:
        """Получить список задач"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if status and category:
            cursor.execute("""
                SELECT task_id, created_by, photo_before_id, photo_before_path, comment, 
                       status, category, completed_by, photo_after_id, photo_after_path, created_at, completed_at
                FROM tasks WHERE status = ? AND category = ? ORDER BY created_at DESC
            """, (status, category))
        elif status:
            cursor.execute("""
                SELECT task_id, created_by, photo_before_id, photo_before_path, comment, 
                       status, category, completed_by, photo_after_id, photo_after_path, created_at, completed_at
                FROM tasks WHERE status = ? ORDER BY created_at DESC
            """, (status,))
        elif category:
            cursor.execute("""
                SELECT task_id, created_by, photo_before_id, photo_before_path, comment, 
                       status, category, completed_by, photo_after_id, photo_after_path, created_at, completed_at
                FROM tasks WHERE category = ? ORDER BY created_at DESC
            """, (category,))
        else:
            cursor.execute("""
                SELECT task_id, created_by, photo_before_id, photo_before_path, comment, 
                       status, category, completed_by, photo_after_id, photo_after_path, created_at, completed_at
                FROM tasks ORDER BY created_at DESC
            """)
        
        rows = cursor.fetchall()
        conn.close()
        
        tasks = []
        for row in rows:
            tasks.append({
                'task_id': row[0],
                'created_by': row[1],
                'photo_before_id': row[2],
                'photo_before_path': row[3],
                'comment': row[4],
                'status': row[5],
                'category': row[6] if len(row) > 6 else None,
                'completed_by': row[7] if len(row) > 7 else None,
                'photo_after_id': row[8] if len(row) > 8 else None,
                'photo_after_path': row[9] if len(row) > 9 else None,
                'created_at': row[10] if len(row) > 10 else None,
                'completed_at': row[11] if len(row) > 11 else None
            })
        return tasks

    def get_task(self, task_id: int) -> Optional[Dict]:
        """Получить задачу по ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT task_id, created_by, photo_before_id, photo_before_path, comment, 
                   status, category, completed_by, photo_after_id, photo_after_path, created_at, completed_at
            FROM tasks WHERE task_id = ?
        """, (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'task_id': row[0],
                'created_by': row[1],
                'photo_before_id': row[2],
                'photo_before_path': row[3],
                'comment': row[4],
                'status': row[5],
                'category': row[6] if len(row) > 6 else None,
                'completed_by': row[7] if len(row) > 7 else None,
                'photo_after_id': row[8] if len(row) > 8 else None,
                'photo_after_path': row[9] if len(row) > 9 else None,
                'created_at': row[10] if len(row) > 10 else None,
                'completed_at': row[11] if len(row) > 11 else None
            }
        return None

    def update_task_status(self, task_id: int, status: str, completed_by: Optional[int] = None,
                          photo_after_id: Optional[str] = None, photo_after_path: Optional[str] = None):
        """Обновить статус задачи"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if status == "Выполнено":
            cursor.execute("""
                UPDATE tasks 
                SET status = ?, completed_by = ?, photo_after_id = ?, photo_after_path = ?, completed_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (status, completed_by, photo_after_id, photo_after_path, task_id))
        else:
            cursor.execute("""
                UPDATE tasks SET status = ? WHERE task_id = ?
            """, (status, task_id))
        
        conn.commit()
        conn.close()

    def get_all_executors(self) -> List[int]:
        """Получить список всех исполнителей (user_id)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE role = 'executor'")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    def get_all_managers(self) -> List[int]:
        """Получить список всех менеджеров (user_id)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE role = 'manager'")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]

    def update_task_comment(self, task_id: int, comment: str):
        """Обновить комментарий задачи"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET comment = ? WHERE task_id = ?", (comment, task_id))
        conn.commit()
        conn.close()

    def update_task_photo(self, task_id: int, photo_id: str, photo_path: str):
        """Обновить фотографию задачи"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET photo_before_id = ?, photo_before_path = ? 
            WHERE task_id = ?
        """, (photo_id, photo_path, task_id))
        conn.commit()
        conn.close()

    def reset_task_to_new(self, task_id: int):
        """Сбросить задачу в статус 'Новая' и удалить данные о выполнении"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE tasks 
            SET status = 'Новая', 
                completed_by = NULL, 
                photo_after_id = NULL, 
                photo_after_path = NULL, 
                completed_at = NULL
            WHERE task_id = ?
        """, (task_id,))
        conn.commit()
        conn.close()

    def delete_task(self, task_id: int):
        """Удалить задачу и все связанные фото"""
        conn = self.get_connection()
        cursor = conn.cursor()
        # Сначала удаляем все фото задачи (на всякий случай, хотя CASCADE тоже работает)
        self.delete_all_task_photos(task_id)
        # Затем удаляем саму задачу (CASCADE автоматически удалит оставшиеся фото, если они есть)
        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()

