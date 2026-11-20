# 光伏电站限电事件与损失电量复算

给新能源场站运营分析员使用。仅用有效对照逆变器和相同辐照区间拟合基线；重叠限电事件先求并集再积分。

七个业务模块：遥测采信、设备映射、事件切片、基线拟合、损失核算、能量对账、运行归档。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

访问 http://localhost:18244 。启动直接载入现场脏批。切换干净样例、旧编码样例和混用单位/中文列名样例（mixed）可对照核验。完整对照批INV-A重叠事件取并集后30分钟，基线100kW、实际60kW，损失20kWh；无合格对照或遥测冲突必须保持未定，不能填0。

各模块页面对应 `/<模块英文名>`，各模块执行入口为 `POST /api/<模块英文名>`，不传参即可独立演示。完整运行 `POST /api/runs` 支持 `dataset`（dirty/clean/legacy/mixed）、`csv_text`、`overrides` 与 `mapping_version` 参数。批次历史 `GET /api/runs`，详情 `GET /api/runs/{run_id}`，映射版本清单 `GET /api/mappings`。

列别名与功率单位按版本化注册表 `app/mapping.py` 裁定：登记别名/单位兼容换算并留血缘（原列、原值、原单位、系数、依据）；语义未证实的列（如“发电量”）和单位（如 W）整行进待查隔离，不进基线与损失。同一设备同一时刻在换算为 kW 后比较，等价跨单位重复合并为一条（`SAMPLE_DUPLICATE`），冲突双隔离（`SAMPLE_CONFLICT`），绝不产生两条观测。批号 digest 同时纳入规则版本与映射版本：更新规则/映射后重跑同批生成新批号，旧批与已复核记录原样保留；已复核批重复提交返回 409；切换映射版本不兼容时返回 409 并保留旧版结果（`fallback_run_id`）。

同输入与规则版本生成相同批号，只保留一条批次。复核入口 `POST /api/runs/{run_id}/review` 提交当前 `revision`，陈旧提交409。归档包只有一个下载入口 `GET /api/export/{run_id}`，含证据和运行摘要。原始隔离在页面同屏显示。

SQLite使用命名卷，容器重启后保留历史。要重建演示可在Compose中改用新的卷名称，保留旧卷。

源码在 `app/`，样例在 `sample_data/`，测试在 `tests/`；定义见 `docs/DATA-DICTIONARY.md`，模块和边界测试对应关系见 `docs/DEPTH.md`。输入上限2MB，属于离线复核工具。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。
