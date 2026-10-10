# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import aiosqlite

from sentinel_engine.base import IdentityConnector


class SQLiteIdentityConnector(IdentityConnector):
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_tags(self, user_id: str) -> set[str]:
        async with (
            aiosqlite.connect(self.db_path) as db,
            db.execute("SELECT tag FROM permissions WHERE user_id = ?", (user_id,)) as cursor,
        ):
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
