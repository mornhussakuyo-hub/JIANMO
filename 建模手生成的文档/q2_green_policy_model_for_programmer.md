# Q2 TDSDHVRPTW-GAC 编程手版本

对应主模型文件：

`/home/hanchen/华中杯A题（稳健codex）/analysis/06_model_formulation_pretty(1).md`

本文件只服务代码实现，保留 Q2 所需的模型接口、变量口径、约束实现和输出字段。Q2 在 Q1 `TDSDHVRPTW` 基础上加入绿色配送区准入约束，形成：

$$
\text{TDSDHVRPTW-GAC}
$$

其中 `GAC` 表示 Green Access Constraint。本文件不提前给出 Q2 运行结论；成本变化、车型变化、迟到变化和碳排变化必须等待编程手运行并复核后再填写。

## 1. 模型范围

Q2 解决的问题是：在 Q1 已有的时变路网、拆分配送、异构车队、时间窗、能耗和碳成本模型基础上，加入绿色配送区燃油车禁入规则，重新决定车辆启用、客户服务比例、车辆访问顺序、到达时刻和弧段载荷。

Q2 的目标函数结构不变：

$$
Z_2=C_{start}+C_{energy}+C_{carbon}+C_{wait}+C_{late}
$$

政策影响不通过新增成本项表达，而是通过新增可行性约束改变可行域。代码实现中不能把绿色准入违约次数加入目标函数；它只用于可行性门禁和输出校验。

## 2. 建模假设

Q2 继承 Q1 已有的基础模型口径，不在本文件重写 Q1 假设。这里仅列出 Q2 为表达绿色准入政策而额外加入的建模边界。

若 Q1/Q2 求解器在执行层允许车辆返仓后复用，本文件只继承该执行层口径：车辆复用发生在路线排程与结果汇总阶段，不新增 Q2 主模型变量，也不改变绿色准入约束公式。同一 `vehicle_instance_id` 的多条执行路线必须满足 `[depart_time, return_time]` 时间区间不重叠；`startup_cost` 按唯一 `vehicle_instance_id` 去重统计，不得按 `route_id` 重复累计；`route_count` 与 `used_vehicle_count` 必须分开输出。当前 Q1 代码中的 `vehicle_id` 与本文档的 `vehicle_instance_id` 含义相同，均表示具体物理车辆实例。Q1/Q2 政策对比必须使用同一复用开关、同一固定成本去重口径和同一数据口径。

| 编号 | 假设内容 | 实现含义 |
|---|---|---|
| P1 | 绿色区客户集合在计划前固定 | 直接使用清洗后的 `is_green` 字段生成 $G_j$，不在求解中重新识别绿色区 |
| P2 | 绿色准入政策只对燃油车生效 | `energy_type == "燃油"` 的车辆受 GAC 约束，新能源车不触发该禁入规则 |
| P3 | 准入判定使用车辆到达绿色区客户的时刻 | 燃油车若在禁入时段到达绿色区客户，该候选服务顺序直接不可行 |
| P4 | 政策只改变可行路径集合 | 不改变需求、容量、服务时间、能源价格、碳价格，也不新增成本项 |

## 3. 输入接口

### 3.1 客户层输入

若沿用当前 `/home/hanchen/JIANMO/src` 的 Q1 代码，客户层输入来自：

- `cleaned_data/customers.json`

若另行导出 `outputs/cleaned/customer_demand.csv` 和 `outputs/cleaned/customer_profile.csv`，它们只能作为上述 JSON 的派生标准表，字段口径必须与当前代码对象一致。

每个客户 $j$ 至少需要以下字段。

| 字段 | 模型对象 | 单位 | 说明 |
|---|---|---|---|
| `customer_id` | $j$ | - | 客户编号 |
| `total_weight` | $W_j$ | kg | 客户聚合重量需求 |
| `total_volume` | $V_j$ | m$^3$ | 客户聚合体积需求 |
| `window_start` | $e_j$ | `HH:MM` | 展示用最早服务时间 |
| `window_end` | $l_j$ | `HH:MM` | 展示用最晚服务时间 |
| `window_start_min` | $e_j$ 的实现值 | min | 绝对分钟口径 |
| `window_end_min` | $l_j$ 的实现值 | min | 绝对分钟口径 |
| `is_green` | $G_j$ | - | 绿色区标记，1 表示绿色区 |
| `has_orders` | 是否进入 $N^+$ | - | 只让正需求客户进入主模型 |
| `order_count` | 派生统计 | - | 客户订单数 |

客户集合为：

$$
N^+=\{j\in N\mid W_j>0\ \text{or}\ V_j>0\}
$$

绿色区客户集合为：

$$
N^{green}=\{j\in N^+\mid G_j=1\}
$$

当前主模型口径中，清洗后按坐标规则识别出的绿色区客户总数为 `15`，进入 Q1/Q2 主模型的正需求绿色区客户为 `12`。这是输入口径，不是运行结论。

### 3.2 执行层任务块输入

当前 Q1 代码由 `task_builder` 从 `cleaned_data/customers.json` 构造拆分配送的执行层任务块。若额外导出 `outputs/cleaned/service_units.csv`，只能作为中间结果或调试表，不能改变任务块字段含义。

| 字段 | 模型对象 | 说明 |
|---|---|---|
| `service_unit_id` | 执行层任务编号 | 不是论文主模型变量 |
| `customer_id` | $j$ | 对应客户 |
| `part_index`, `part_count` | 拆分索引 | 用于将服务块聚合回客户 |
| `weight`, `volume` | 服务块需求 | 对应客户需求的一部分 |
| `window_start_min`, `window_end_min` | 时间窗实现值 | 代码分钟口径 |
| `is_green` | $G_j$ | 必须与客户层绿色区标记一致 |
| `x_km`, `y_km` | 坐标 | 用于审查或可视化 |

注意：`service_unit` 只属于启发式实现层。数学模型仍以客户 $j$ 和服务比例 $\lambda_{jm}$ 表示拆分配送。

### 3.3 车辆输入

若沿用当前 Q1 代码，车辆输入来自 `cleaned_data/vehicles.json`，并由 `available_count` 展开为具体车辆实例。若另行导出 `outputs/cleaned/vehicles.csv`，应保持同一字段口径。

| 字段 | 模型对象 | 单位 | 说明 |
|---|---|---|---|
| `k` | $\kappa(m)$ | - | 车型编号 |
| `vehicle_type_id` | 车型标识 | - | 原始车型 ID |
| `energy_type` | $e(m)$ | - | 燃油或新能源 |
| `max_weight` | $Q_m^w$ | kg | 最大载重 |
| `max_volume` | $Q_m^v$ | m$^3$ | 最大容积 |
| `available_count` | 车辆实例数 | 辆 | 生成车辆实例集合 $M$ |
| `startup_cost` | $f_m$ | 元 | 固定启用成本 |

燃油车标记为：

$$
F_m=
\begin{cases}
1, & e(m)=\text{燃油}\\
0, & e(m)=\text{新能源}
\end{cases}
$$

燃油车集合为：

$$
M^{fuel}=\{m\in M\mid F_m=1\}
$$

### 3.4 距离输入

若沿用当前 Q1 代码，距离输入来自 `cleaned_data/distance_matrix.csv`。若另行导出长表 `outputs/cleaned/distance_long.csv`，字段应等价于：

| 字段 | 模型对象 | 说明 |
|---|---|---|
| `from_node` | $i$ | 弧段起点 |
| `to_node` | $j$ | 弧段终点 |
| `distance_km` | $d_{ij}$ | 道路距离 |

节点和弧集合仍为：

$$
V=\{0\}\cup N^+,\qquad
A=\{(i,j)\mid i,j\in V,\ i\neq j\}
$$

## 4. 时间接口

数学模型统一使用相对 `8:00` 的小时数：

$$
8:00=0,\qquad 16:00=8,\qquad 17:00=9
$$

现有代码使用绝对分钟口径：

$$
8:00=480,\qquad 16:00=960,\qquad 17:00=1020
$$

两者换算为：

$$
t^{hour}=\frac{t^{minute}-480}{60}
$$

因此：

$$
t^{hour}=8 \Longleftrightarrow t^{minute}=960
$$

绿色准入政策在数学口径中是：

$$
t_{jm}\notin[0,8),\qquad j\in N^{green},m\in M^{fuel},v_{jm}=1
$$

在代码分钟口径中是：

```text
arrival_min = evaluated_leg.arrival_min

if policy_enabled and energy_type == "燃油" and is_green == 1 and 480 <= arrival_min < 960:
    return infeasible
```

Q2 静态模型中，燃油车不得在禁入时段到达绿色区客户。代码实现采用硬门禁口径：候选路线完成发车时刻、插入顺序和整条路线时序重算后，若任一绿色区服务记录触发上述条件，直接从候选集合中删除。不能在尚未重算发车时间和路线时序时，用临时估计到达时刻过早删除候选。

## 5. 决策变量

Q2 不新增基础路径决策变量，完全继承 Q1 变量。

| 变量 | 类型 | 含义 |
|---|---|---|
| $x_{ijm}$ | binary | 车辆 $m$ 是否走弧 $(i,j)$ |
| $y_m$ | binary | 车辆 $m$ 是否启用 |
| $\lambda_{jm}$ | continuous | 车辆 $m$ 承担客户 $j$ 的需求比例 |
| $q_{ijm}^w,q_{ijm}^v$ | continuous | 弧 $(i,j)$ 上的剩余重量和体积载荷 |
| $t_{jm}$ | continuous | 车辆 $m$ 到达客户 $j$ 的时刻 |
| $D_{im}$ | continuous | 车辆 $m$ 离开节点 $i$ 的时刻；当 $i=0$ 时，$D_{0m}$ 为配送中心实际发车时刻，并继承 Q1 的 $0\le D_{0m}\le T y_m$ |
| $T_m^{ret}$ | continuous | 车辆 $m$ 返回配送中心的时刻 |
| $\varepsilon_{jm}^+,\varepsilon_{jm}^-$ | continuous | 等待量和迟到量 |
| $u_{jm}$ | continuous | MTZ 路径序号变量 |

访问指示量：

$$
v_{jm}=\sum_{i\in V,i\neq j}x_{ijm}
$$

配送量：

$$
\delta_{jm}^w=\lambda_{jm}W_j,\qquad
\delta_{jm}^v=\lambda_{jm}V_j
$$

## 6. 新增政策参数

| 参数 | 类型 | 含义 | 代码字段或常量 |
|---|---|---|---|
| $G_j$ | binary parameter | 客户 $j$ 是否属于绿色区 | `is_green` |
| $F_m$ | binary parameter | 车辆 $m$ 是否为燃油车 | `energy_type == "燃油"` |
| $N^{green}$ | set | 正需求绿色区客户集合 | 从 $N^+$ 中筛选 |
| $M^{fuel}$ | set | 燃油车实例集合 | 从 $M$ 中筛选 |
| $t^{GAC}_{start}$ | parameter | 禁入开始时刻 | 数学 0，代码 `8*60` |
| $t^{GAC}_{end}$ | parameter | 禁入结束时刻 | 数学 8，代码 `16*60` |

其中 $G_j,F_m$ 是输入标记，不是决策变量。

## 7. 目标函数

Q2 目标函数保持 Q1 的五项成本结构：

$$
\min Z_2=C_{start}+C_{energy}+C_{carbon}+C_{wait}+C_{late}
$$

其中：

$$
C_{start}=\sum_{m\in M} f_my_m
$$

$$
C_{energy}=\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{energy}x_{ijm}
$$

$$
C_{carbon}=\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{carbon}x_{ijm}
$$

$$
C_{wait}=p^{wait}\sum_{m\in M}\sum_{j\in N^+}\varepsilon_{jm}^+
$$

$$
C_{late}=p^{late}\sum_{m\in M}\sum_{j\in N^+}\varepsilon_{jm}^-
$$

政策增量只作为输出指标：

$$
\Delta Z_{21}=Z_2-Z_1
$$

## 8. 约束

### 8.1 继承 Q1 约束

Q2 必须继承 Q1 的全部主约束：

1. 需求满足与拆分配送；
2. 路径连续与车辆启用；
3. 重量与体积载荷流守恒；
4. 容量约束；
5. 时变时间传播；
6. 软时间窗；
7. 子回路消除；
8. 车型可用数量约束；
9. 时间变量关闭和变量定义域。

这些约束的公式与 Q1 编程手文件一致，不在 Q2 中改写含义。代码实现若按 `available_count` 展开车辆实例集合，则车型可用数量约束由实例集合自然保证；若按车型数量变量建模，则必须显式约束各车型启用车辆数不超过 `available_count`。

### 8.2 绿色准入约束

对所有绿色区客户和燃油车：

$$
t_{jm}\ge 8-\Omega(1-v_{jm}),
\qquad \forall j\in N^{green},\forall m\in M^{fuel}
$$

含义：

- 若 $v_{jm}=1$，燃油车 $m$ 访问绿色区客户 $j$，则必须满足 $t_{jm}\ge 8$，即 16:00 后到达。
- 若 $v_{jm}=0$，车辆不访问该客户，约束由大常数自动松弛。
- 新能源车不属于 $M^{fuel}$，不受该约束限制。
- 若燃油车到达绿色区客户的时刻早于 `16:00`，该候选服务顺序不可行。

### 8.3 启发式候选可行性检查

若代码使用启发式而不是显式 MIP 求解，应先构造候选路线，确定或重算 `departure_min`，再用完整路线评价函数得到每个服务点的实际 `arrival_min`。绿色准入硬门禁必须基于这个重算后的 `arrival_min`，不能基于未调整发车时间、未重排路线顺序前的临时估计值提前删候选。

```text
candidate_route = rebuild_route_with_candidate_insert(...)
candidate_route.departure_min = choose_or_adjust_departure_min(candidate_route)
evaluation = evaluate_route(candidate_route)

for leg in evaluation.service_legs:
    arrival_min = leg.arrival_min
    if policy_enabled and vehicle.energy_type == "燃油" and leg.is_green:
        if POLICY_BLOCK_START_MIN <= arrival_min < POLICY_BLOCK_END_MIN:
            return None

    wait_min = max(0, leg.window_start_min - arrival_min)
    service_start_min = arrival_min + wait_min
    late_min = max(0, arrival_min - leg.window_end_min)
```

硬门禁检查发生在车辆选择和客户插入两个阶段：

1. 单客户种子车辆选择时，先对种子路线重算发车时刻和到达时刻，再删除违反 GAC 的燃油车候选；
2. 路线扩展插入下一服务任务时，先形成完整候选路线并重新评价整条路线时序，再做 GAC 门禁；
3. 只要燃油车在重算后的实际 `arrival_min` 中于 `16:00` 前到达绿色区客户，该候选路线即不可行。

## 9. 大致计算思路

### 9.1 数据准备

1. 读取客户、车辆和距离矩阵；若使用当前 Q1 代码，输入文件为 `cleaned_data/customers.json`、`cleaned_data/vehicles.json` 和 `cleaned_data/distance_matrix.csv`。
2. 仅保留正需求客户进入 $N^+$。
3. 根据 `is_green` 构造 $G_j$ 和 $N^{green}$。
4. 根据 `energy_type` 构造 $F_m$、$M^{fuel}$ 和 $M^{elec}$。
5. 对车辆类型展开车辆实例集合 $M$。
6. 复用 Q1 的旅行时间、能耗、碳成本和时间窗计算函数。

### 9.2 求解接口

建议接口：

```text
build_plan(service_units, vehicles, distance, policy_enabled=True, scenario_name="q2_policy")
```

其中：

| 参数 | 含义 |
|---|---|
| `service_units` | 拆分后的执行层任务块 |
| `vehicles` | 车辆类型及可用数量 |
| `distance` | 距离矩阵 |
| `policy_enabled` | 是否启用 Q2 绿色准入约束 |
| `scenario_name` | 输出场景名 |

求解流程：

1. 初始化未服务任务集合。
2. 为每个车辆实例维护当前节点、当前时刻、剩余容量和已服务任务。
3. 每次生成候选插入后，重算候选路线的发车时刻、访问顺序和完整时序。
4. 基于重算后的实际 `arrival_min` 检查 GAC；若触发禁入条件，则直接删除该候选。
5. 对剩余候选汇总距离、时间窗等待、迟到、能耗和碳成本。
6. 生成路线弧段表和车辆汇总表。
7. 与同口径 Q1 结果对比，生成政策对比指标。

## 10. 输出字段

输出字段必须能回到模型变量或派生量。字段名可按代码习惯调整，但每个字段都必须有明确来源。

### 10.1 问题二交付项与输出变量对应表

| 问题二要求 | 建议输出表 | 具体输出字段 | 对应模型对象 | 说明 |
|---|---|---|---|---|
| 政策约束后的车辆路径 | 路线弧段表 | `route_id`, `vehicle_instance_id`, `energy_type`, `seq`, `from_node`, `to_node`, `arrival_time`, `service_start_time`, `service_end_time` | $x_{ijm},t_{jm},D_{jm},T_m^{ret}$ | 按车辆和顺序得到完整路径 |
| 客户服务分配 | 客户服务表 | `customer_id`, `vehicle_instance_id`, `lambda`, `served_weight`, `served_volume`, `visit_flag` | $\lambda_{jm},\delta_{jm}^w,\delta_{jm}^v,v_{jm}$ | 可由执行层任务块聚合回客户层 |
| 绿色区服务结构 | 政策服务表 | `customer_id`, `is_green`, `energy_type`, `green_fuel_service_count`, `green_new_energy_service_count` | $G_j,F_m,v_{jm}$ | 统计绿色区由燃油车或新能源车服务的结构 |
| 政策增量成本 | 政策对比表 | `delta_total_cost`, `delta_startup_cost`, `delta_energy_cost`, `delta_carbon_cost`, `delta_wait_cost`, `delta_late_cost` | $\Delta Z_{21}$ 及成本分项差值 | 只在代码运行后填值 |
| 可行性门禁 | 政策校验表 | `policy_enabled`, `green_violation_count`, `unserved_service_units` | GAC 检查、服务完成检查 | 严格 Q2 中绿色准入违约应被判为不可行 |

### 10.2 路线弧段表

现有输出可使用以下字段。当前代码若使用 `vehicle_id` 字段，可直接视为本文档中的 `vehicle_instance_id`。

| 输出字段 | 计算或生成方式 | 对应模型对象 |
|---|---|---|
| `scenario` | 场景名 | 输出标识 |
| `route_id` | 路线编号 | 派生编号 |
| `vehicle_instance_id` | 车辆实例编号 | $m$ |
| `vehicle_k`, `vehicle_type_id` | 车型编号 | $\kappa(m)$ |
| `energy_type` | 能源类型 | $e(m),F_m$ |
| `seq` | 路线访问顺序 | $u_{jm}$ 或执行层顺序 |
| `from_node`, `to_node` | 使用弧起点和终点 | $x_{ijm}=1$ 的弧 |
| `service_unit_id` | 执行层服务任务 | 启发式任务块 |
| `customer_id` | 客户编号 | $j$ |
| `depart_time` | 离开时刻；仓库弧取 $D_{0m}$，客户弧取 $D_{im}$ | $D_{0m}$ 或 $D_{im}$ |
| `arrival_time` | 到达时刻 | $t_{jm}$ 或 $T_m^{ret}$ |
| `service_start_time` | 实际开始服务时刻 | $t_{jm}+\varepsilon_{jm}^+$ |
| `service_end_time` | 实际完成服务时刻 | $D_{jm}$ |
| `distance_km` | 弧段距离 | $d_{ij}$ |
| `weight_served`, `volume_served` | 本弧服务量 | $\delta_{jm}^w,\delta_{jm}^v$ 的执行层分量 |
| `wait_min`, `late_min` | 等待和迟到 | $\varepsilon_{jm}^+,\varepsilon_{jm}^-$ 的分钟实现 |
| `leg_energy_cost`, `leg_carbon_cost` | 弧段能耗与碳成本 | $c_{ijm}^{energy},c_{ijm}^{carbon}$ |

### 10.3 路线与车辆成本汇总表

若输出表以 `route_id` 为行粒度，则该表首先是路线汇总表；同一 `vehicle_instance_id` 可能对应多条执行路线。此时能耗、碳、等待和迟到成本可按路线累计，但固定启用成本不能按路线重复累计。Q2 总成本中的 `startup_cost` 以 KPI 汇总表为准，必须按唯一 `vehicle_instance_id` 去重；路线行中的 `startup_cost` 只能作为车辆级标记或分摊展示字段，不能直接逐行求和作为总固定成本。

| 输出字段 | 计算或生成方式 | 对应模型对象 |
|---|---|---|
| `scenario` | 场景名 | 输出标识 |
| `route_id` | 路线编号 | 派生编号 |
| `vehicle_instance_id` | 车辆实例编号 | $m$ |
| `vehicle_k`, `vehicle_type_id` | 车型编号 | $\kappa(m)$ |
| `energy_type` | 能源类型 | $e(m),F_m$ |
| `stops` | 客户服务次数 | $\sum_j v_{jm}$ 的执行层计数 |
| `total_distance_km` | 单车路线距离 | $\sum_{(i,j)}d_{ij}x_{ijm}$ |
| `startup_cost` | 固定启用成本展示字段；车辆复用时同一 `vehicle_instance_id` 只允许计一次，不能按 `route_id` 重复累计 | $f_my_m$ |
| `energy_cost` | 单车能耗成本 | $\sum c_{ijm}^{energy}x_{ijm}$ |
| `carbon_cost` | 单车碳成本 | $\sum c_{ijm}^{carbon}x_{ijm}$ |
| `wait_cost` | 单车等待成本 | $p^{wait}\sum_j\varepsilon_{jm}^+$ |
| `late_cost` | 单车迟到成本 | $p^{late}\sum_j\varepsilon_{jm}^-$ |
| `total_cost` | 路线或车辆成本；含不含固定启用成本必须在输出说明中标明，总成本以 KPI 去重口径为准 | 成本分项求和 |
| `finish_time` | 车辆返仓或路线完成时刻 | $T_m^{ret}$ |

### 10.4 KPI 汇总与政策对比表

KPI 汇总至少包含：

| 字段 | 含义 | 来源 |
|---|---|---|
| `policy_enabled` | 是否启用 Q2 政策 | 场景参数 |
| `total_cost` | Q2 总成本 | $Z_2$ |
| `startup_cost` | 总固定成本；执行层车辆复用时按唯一 `vehicle_instance_id` 或当前代码 `vehicle_id` 去重 | $C_{start}$ |
| `energy_cost` | 总能耗成本 | $C_{energy}$ |
| `carbon_cost` | 总碳成本 | $C_{carbon}$ |
| `wait_cost` | 总等待成本 | $C_{wait}$ |
| `late_cost` | 总迟到成本 | $C_{late}$ |
| `total_distance_km` | 总行驶距离 | 路线弧段距离求和 |
| `served_service_units` | 已服务任务块数 | 执行层统计 |
| `unserved_service_units` | 未服务任务块数 | 执行层统计 |
| `route_count` | 执行路线数，不等同于启用车辆数 | 路线表计数 |
| `used_vehicle_count` | 启用物理车辆数；执行层车辆复用时按唯一 `vehicle_instance_id` 或当前代码 `vehicle_id` 去重 | 车辆汇总表计数 |
| `late_stop_count` | 迟到服务次数 | `late_min > 0` 的服务计数 |
| `wait_stop_count` | 等待服务次数 | `wait_min > 0` 的服务计数 |

政策对比表至少包含：

| 字段 | 含义 | 填写规则 |
|---|---|---|
| `delta_total_cost` | $Z_2-Z_1$ | 运行后由同口径 Q2 减 Q1 |
| `delta_distance_km` | 总里程差 | 运行后填 |
| `delta_route_count` | 路线数差 | 运行后填 |
| `delta_used_vehicle_count` | 启用车辆数差 | 运行后由同口径 Q2 减 Q1 |
| `delta_late_stop_count` | 迟到服务次数差 | 运行后填 |
| `delta_energy_cost` | 能耗成本差 | 运行后填 |
| `delta_carbon_cost` | 碳成本差 | 运行后填 |
| `delta_wait_cost` | 等待成本差 | 运行后填 |
| `delta_late_cost` | 迟到成本差 | 运行后填 |
| `green_violation_count` | 绿色准入违约次数 | 按燃油车到达绿色区客户时刻检查；严格 GAC 下应作为硬门禁 |
| `green_fuel_service_count` | 绿色区燃油车服务次数 | 运行后统计 |
| `green_new_energy_service_count` | 绿色区新能源车服务次数 | 运行后统计 |

## 11. 一致性校验

Q2 编程实现完成后至少检查：

1. Q2 只在 Q1 基础上新增 GAC，不改写 Q1 的基础目标和约束。
2. $G_j$ 与 `is_green` 一一对应。
3. $F_m$ 与 `energy_type == "燃油"` 一一对应。
4. 数学小时口径和代码分钟口径换算正确。
5. 每条燃油车服务绿色区客户的记录都满足重算后的实际 `arrival_min` 不在禁入区间内；候选路线必须在完成发车时刻和整条路线时序重算后再做 GAC 检查，不能用未重算的临时到达时刻提前删除候选。
6. 所有正需求任务都被服务，或在输出中显式列为未服务。
7. 成本分项之和等于 `total_cost`。
8. 政策对比只使用同一求解链、同一数据口径下的 Q1/Q2 结果。
9. 各车型启用车辆数不得超过输入中的 `available_count`。
10. 若允许车辆复用，`startup_cost` 必须按唯一 `vehicle_instance_id` 或当前代码 `vehicle_id` 去重，不能按 `route_id` 重复累计。

## 12. 一致性声明

本文件与主模型文件 `06_model_formulation_pretty(1).md` 的 Q2 口径保持一致：

1. Q2 继承 Q1 的输入、变量、时间传播、能耗、碳成本、容量和时间窗口径。
2. Q2 新增对象仅为 $G_j,F_m,N^{green},M^{fuel}$ 和 GAC。
3. Q2 不提前给出政策效果结论。
4. 运行结论必须由代码输出和后续复核决定。
