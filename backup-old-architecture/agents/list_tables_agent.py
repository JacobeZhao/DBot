from rich.console import Console
from backend.state import DataSpeakState
from backend.tools.schema_tools import GetTableSchemaTool, get_table_metadata, INTERNAL_TABLES


SYSTEM_COLUMNS = {"id", "uuid", "创建时间", "更新时间", "created_at", "updated_at"}

console = Console()


def list_tables_agent(state: DataSpeakState) -> DataSpeakState:
    console.print("[bold green][LIST_TABLES][/bold green] 生成表列表...")

    schema_info = GetTableSchemaTool().run()
    metadata = get_table_metadata()

    tables = [t for t in schema_info if t not in INTERNAL_TABLES]

    if not tables:
        return {**state, "final_response": "当前数据库中没有任何表。您可以说「新建一个...表」来创建第一张表。"}

    lines = [f"当前数据库共有 {len(tables)} 张表：\n"]
    for i, table in enumerate(tables, 1):
        meta = metadata.get(table, {})
        desc = meta.get("description", "")
        aliases = [a for a in meta.get("aliases", []) if a]
        columns = schema_info[table]
        col_names = [c["name"] for c in columns if c["name"] not in SYSTEM_COLUMNS]

        header = f"{i}. **{table}**"
        if desc:
            header += f"  ——  {desc}"
        lines.append(header)
        if aliases:
            lines.append(f"   别名：{', '.join(aliases)}")
        lines.append(f"   字段：{', '.join(col_names)}")
        lines.append("")

    lines.append("您可以直接用描述或别名来操作这些表，例如：")
    lines.append("「记录一笔花销」会自动匹配 expenses 表。")

    console.print(f"[bold green][LIST_TABLES][/bold green] 列出 {len(tables)} 张表")
    return {**state, "final_response": "\n".join(lines)}
