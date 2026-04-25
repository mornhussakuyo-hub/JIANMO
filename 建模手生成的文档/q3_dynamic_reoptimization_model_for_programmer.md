# Q3 Dynamic TDSDHVRPTW 编程手版本

本文件是 Q3 编程实现的自包含交付文件。编程手只阅读本文件，也应能完整实现 Q3 的输入切片、事件更新、残余客户重优化、约束检查、扰动指标和输出字段；不得再依赖主模型文件、队友说明或论文手文件补约束。

一致性参考文件为：

- `/home/hanchen/华中杯A题（稳健codex）/analysis/06_model_formulation_pretty(1).md`
- `/home/hanchen/华中杯A题（稳健codex）/analysis/q3_dynamic_reoptimization_model_for_teammate.md`

这些文件只用于交叉核对表述；若实现时只看本文件，以下数学对象和硬约束已经完整给出。本文件按 Q1 程序员文件的结构组织，只服务代码实现。Q3 基于 Q1 执行状态，不继承 Q2 绿色准入，不预写运行结论。

单文件实现必须覆盖：

1. 读取 Q1 执行状态，冻结已完成、在途和正在服务的服务单元；
2. 将新增、取消、地址变更、时间窗调整事件先作用到服务单元状态层，再聚合为残余客户集合 $N^{rem}(t_r)$；
3. 残余优化只在客户层建模，主变量为 $x_{ijm}^{(r)},y_m^{(r)},\lambda_{jm}^{(r)},q_{ijm}^{w,(r)},q_{ijm}^{v,(r)},t_{jm}^{(r)},S_{jm}^{(r)},D_{jm}^{(r)},T_m^{ret,(r)},u_{jm}^{(r)}$；
4. 已离仓车辆只能服务事件时刻当前执行路线中车上已装载且未完成的服务单元对应残余比例，不能把同一物理车辆未来尚未出发路线算作车上货；
5. Q3 数学主模型不建模中途回仓补货，也不建模同一物理车辆多趟复用；执行层复用必须硬校验时间不重叠，并按唯一物理车辆去重固定成本；
6. 残余模型必须包含需求满足、拆分比例、路径连续、车辆启用、载荷流、容量、车上货物上界、时间传播、最终返仓、软时间窗、MTZ 和变量域约束；
7. 扰动指标只作为 KPI 输出，不进入成本目标；`disruption_proxy` 必须按本文的 $A_m^{cmp}(t_r)$、$\Delta^{arc}$ 和 $\Delta^{assign}$ 口径计算；
8. 输出必须包含服务单元到残余客户映射、车上货物集合、残余路线、成本分项、扰动字段和一致性校验结果。

## 1. 模型范围

Q3 主模型为：

$$
\text{Dynamic TDSDHVRPTW}
$$

即在 Q1 已生成且正在执行的路线基础上，面对新增订单、取消订单、地址变化或时间窗变化事件，冻结已执行事实，只对事件时刻后的残余部分做滚动重优化。

正确计算链为：

```text
Q1 route plan
-> event at t_r
-> frozen_prefix by service_unit_id
-> vehicle states + onboard customer sets
-> residual_service_units
-> aggregate to residual_customers
-> customer-level residual reoptimization
-> q3 rolling plan + disruption metrics
```

关键边界：

1. `service_unit_id` 只用于状态切片、事件记录、冻结记录、输出追踪和聚合映射。
2. 残余优化节点是客户 `customer_id`，不是 `service_unit_id`。
3. 已离仓车辆只能服务事件时刻车上服务单元对应的残余比例。
4. 新增订单或非车上承诺货物只能由事件时刻在仓或未启动车辆装载；车辆返仓后复用只属于执行层排程口径，且必须校验同一物理车辆路线时间不重叠、固定成本按唯一物理车辆去重。
5. 扰动幅度默认不进入成本目标，只作为稳定性 KPI 输出。

Q3 数学主模型中的车辆 $m$ 只表示残余优化中的一次路线执行，不刻画同一物理车辆的多趟复用。同一物理车辆多趟复用仅作为启发式执行层排程后处理，要求同一 `vehicle_id` 或 `vehicle_instance_id` 的多条执行路线时间不重叠，并在成本统计中按唯一物理车辆计固定成本。

默认残余成本为：

$$
Z_{\text{rem}}(t_r)
=C_{\text{start}}^{(r)}
+C_{\text{energy}}^{(r)}
+C_{\text{carbon}}^{(r)}
+C_{\text{wait}}^{(r)}
+C_{\text{late}}^{(r)}
$$

总成本为：

$$
Z_3(t_r)=C_{\text{fix}}(t_r)+Z_{\text{rem}}(t_r)
$$

## 2. 建模假设

| 编号 | 假设内容 | 实现含义 |
|---|---|---|
| D1 | 事件在触发时刻即时可见 | 事件表在 `event_time_min` 进入求解器 |
| D2 | 已完成服务冻结 | `service_end_time_min <= event_time_min` 的记录不重排 |
| D3 | 在途或正在服务任务保守冻结 | 先完成当前弧段或当前服务，再进入车辆残余状态 |
| D4 | 残余任务只包含未冻结和事件任务 | 冻结服务单元不得在残余集合重复出现 |
| D5 | 车辆从有效位置继续调度 | 残余起点为 `current_node`，可用时刻为 `available_time_min` |
| D6 | 固定成本不重复计 | 已启动车辆残余阶段 `startup_cost=0`，未启动车辆新启用才计固定成本 |
| D7 | 不允许凭空装载 | 新增订单由在仓或未启动车辆服务；已离仓车辆不得在数学主模型中中途补货 |
| D8 | Q3 无 GAC | 不调用 Q2 绿色准入检查，不输出绿色违约作为 Q3 主门禁 |

若代码为了简化允许已出车车辆直接服务非车上货物，必须在代码说明和论文中声明为执行层“虚拟装载”或车辆复用修复，且不得写入 Q3 数学主模型。默认实现不允许。

若执行层采用同一物理车辆返仓后再执行多条路线的后处理，该复用不进入上方数学主模型。代码必须额外校验同一 `vehicle_id` 或 `vehicle_instance_id` 下的路线时间区间不重叠，且固定启动成本按唯一物理车辆去重。

### 2.1 Q3 符号总表

本表用于保证编程手文件自洽。后文出现的 Q3 专用符号均应能在本表或 Q1 继承符号行中找到定义。

| 类别 | 符号 | 代码对象 | 含义 |
|---|---|---|---|
| 索引 | $0$ | depot node | 配送中心 |
| 索引 | $j,k$ | `customer_id` | 客户节点 |
| 索引 | $u$ | `service_unit_id` | 服务单元，只用于状态切片和追踪 |
| 索引 | $m$ | `vehicle_instance_id` | 车辆实例 |
| 索引 | $t_r$ | `event_time_min` | 事件触发时刻 |
| 集合 | $N$ | customer set | 客户集合 |
| 集合 | $M,K$ | vehicles, vehicle types | 车辆实例集合、车型集合 |
| 集合 | $U$ | service units | Q1 执行层服务单元集合 |
| 集合 | $M_k$ | vehicles of type k | 车型 $k$ 对应的车辆实例集合 |
| 集合 | $M^{act}(t_r)$ | `active_vehicles` | 事件后仍可调度车辆集合 |
| 事件索引 | $e$ | event row | 事件记录索引，不是服务时间窗下界 |
| 事件集合 | $\mathcal E(t_r)$ | event rows at time | 事件时刻 $t_r$ 触发的事件集合 |
| 事件参数 | $\theta_e,u_e,j_e$ | event type/unit/customer | 事件类型、受影响服务单元、受影响客户 |
| 状态版本 | $(\cdot)^-,(\cdot)^+$ | before/after event | 事件处理前、事件处理后的状态或参数 |
| 状态对象 | $\mathcal S(t_r^-),\mathcal S(t_r^+)$ | state before/after event | 事件前后系统状态 |
| 更新算子 | $\Phi,\Phi_{\theta_e}$ | event update operator | 事件总体更新算子、按事件类型的更新算子 |
| 状态集合 | $U^{done}(t_r)$ | `completed_service_unit_ids` | 事件前已完成服务单元 |
| 状态集合 | $U^{cur}(t_r)$ | `frozen_current_service_unit_ids` | 事件时刻在途或服务中并保守冻结的服务单元 |
| 状态集合 | $U^{fix}(t_r)$ | `frozen_service_unit_ids` | 冻结服务单元 |
| 状态集合 | $U^{new}(t_r)$ | `new_event_service_units` | 事件新增服务单元 |
| 状态集合 | $U^{cancel}(t_r)$ | `cancelled_service_unit_ids` | 事件取消服务单元 |
| 状态集合 | $U^{rem}(t_r)$ | `residual_service_units` | 未冻结且仍需处理的服务单元 |
| 优化集合 | $N^{rem}(t_r)$ | `residual_customers` | 残余客户集合 |
| 映射集合 | $U_j^{rem}(t_r)$ | `source_service_unit_ids` | 残余客户 $j$ 来源服务单元集合 |
| 路径集合 | $V_m^{(r)},A_m^{(r)}$ | residual nodes, arcs | 车辆 $m$ 残余节点和残余弧 |
| 比较集合 | $N^{old,rem}(t_r)$ | `old_residual_customers` | 原计划残余客户集合，不含新增客户 |
| 比较集合 | $A_m^{cmp}(t_r)$ | `comparison_arcs` | 旧计划扰动比较弧集合 |
| 路径状态 | $\Pi^{fix}(t_r)$ | `frozen_rows` | 冻结路径前缀 |
| 路径状态 | $\Pi^{old,rem}(t_r)$ | `old_remaining_plan` | 原计划残余后缀 |
| 服务单元参数 | $c(u)$ | `customer_id` on service unit | 服务单元对应客户 |
| 服务单元参数 | $W_u,V_u,e_u,l_u,s_u$ | service unit demand/window/time | 服务单元重量、体积、时间窗、服务时长 |
| 坐标参数 | $(x_i,y_i)$ | node coordinates | 节点 $i$ 的平面坐标，配送中心和客户均可作为节点 |
| 残余客户参数 | $W_j^{rem},V_j^{rem}$ | `residual_weight`, `residual_volume` | 残余客户聚合重量和体积 |
| 残余客户参数 | $e_j^{rem},l_j^{rem},s_j^{rem}$ | residual window/service time | 残余客户聚合时间窗和服务时长 |
| Q1 继承参数 | $d_{ij},\tau_{ij}(t)$ | distance, travel time function | 距离和时变旅行时间 |
| Q1 继承函数 | $\operatorname{dist}(\cdot,\cdot)$ | distance function | 由两点坐标计算距离 |
| Q1 继承函数 | $c^{energy}(d,m,t),c^{carbon}(\cdot)$ | cost functions | 能耗成本函数、碳成本函数 |
| Q1 继承派生成本 | $c_{ijm}^{energy,(r)},c_{ijm}^{carbon,(r)}$ | residual leg costs | 残余弧段能耗成本、碳成本 |
| Q1 继承参数 | $Q_m^w,Q_m^v,f_m,\text{available}_k$ | vehicle capacity/startup/availability | 车辆重量容量、体积容量、固定启动成本、车型可用数量 |
| Q1 继承参数 | $p^{wait},p^{late},\Omega$ | wait/late cost, big-M | 等待成本、迟到惩罚、大常数 |
| 辅助函数 | $\mathbb I(\cdot)$ | indicator | 条件成立取 1，否则取 0 |
| 车辆状态 | $o_m(t_r)$ | `current_node` | 车辆残余有效起点 |
| 车辆状态 | $t_m^{avail}(t_r)$ | `available_time_min` | 车辆残余可用时刻 |
| 车辆状态 | $a_m(t_r)$ | `started_before_event` | 事件前是否已启动车辆 |
| 车辆状态 | $\chi_m^0(t_r)$ | `at_depot_at_event` | 事件时刻是否在仓 |
| 车辆状态 | $U_m^{onboard}(t_r)$ | `onboard_service_unit_ids` | 车上已装载且尚未完成服务单元 |
| 车辆状态 | $N_m^{onboard}(t_r)$ | `onboard_customer_ids` | 由车上服务单元映射得到的客户 |
| 车辆-客户状态 | $W_{jm}^{onboard}(t_r),V_{jm}^{onboard}(t_r)$ | `onboard_deliverable_weight/volume` | 车辆 $m$ 对残余客户 $j$ 的车上承诺货量 |
| 车辆-客户状态 | $\bar\lambda_{jm}^{onboard}(t_r)$ | `onboard_assignment_cap` | 已离仓可承担比例上界 |
| 车辆状态 | $b_m^w(t_r),b_m^v(t_r)$ | onboard remaining load | 车上剩余重量、体积 |
| 车辆参数 | $B_m^w(t_r),B_m^v(t_r)$ | residual load upper bounds | 残余弧载荷上界 |
| 扰动状态 | $\hat x_{ijm}^{rem}(t_r)$ | old remaining arc used | 原计划残余后缀比较弧使用指示 |
| 扰动状态 | $\hat a_{jm}^{rem}(t_r)$ | old customer assignment | 原计划残余后缀客户服务车辆指示 |
| 决策变量 | $x_{ijm}^{(r)}$ | `residual_route_arcs` | 残余阶段车辆弧选择 |
| 决策变量 | $y_m^{(r)}$ | `vehicle_used_in_residual` | 残余阶段车辆是否使用 |
| 决策变量 | $\lambda_{jm}^{(r)}$ | `customer_assignment_fraction` | 车辆承担残余客户比例 |
| 决策变量 | $q_{ijm}^{w,(r)},q_{ijm}^{v,(r)}$ | residual arc loads | 残余弧段重量、体积载荷 |
| 决策变量 | $t_{jm}^{(r)},S_{jm}^{(r)},D_{jm}^{(r)}$ | arrival/start/depart times | 到达、开始服务、离开客户时刻 |
| 决策变量 | $T_m^{ret,(r)}$ | `finish_time_min` | 最终返仓时刻 |
| 决策变量 | $\varepsilon_{jm}^{+,(r)},\varepsilon_{jm}^{-,(r)}$ | `wait_min`, `late_min` | 等待量和迟到量 |
| 决策变量 | $u_{jm}^{(r)}$ | `customer_visit_order` | 客户层 MTZ 顺序变量 |
| 派生量 | $v_{jm}^{(r)}$ | visit flag | 车辆是否访问残余客户 |
| 成本量 | $C_{\text{fix}},Z_{\text{rem}},Z_3$ | cost summary | 冻结成本、残余成本、Q3 总成本 |
| 成本量 | $C_{\text{start}}^{(r)},C_{\text{energy}}^{(r)},C_{\text{carbon}}^{(r)},C_{\text{wait}}^{(r)},C_{\text{late}}^{(r)}$ | residual cost parts | 残余五类主成本 |
| KPI | $\Delta^{arc},\Delta^{assign},I^{disrupt}$ | disruption metrics | 弧扰动、客户重分配、综合扰动指标 |

## 3. 输入接口

### 3.1 Q1 路线执行表

Q3 必须读取 Q1 路线结果作为事件状态来源。至少需要字段：

| 字段 | 类型 | 含义 | 对应对象 |
|---|---|---|---|
| `scenario` | str | Q1 场景名 | 场景索引 |
| `route_id` | str/int | 执行路线编号 | 输出枚举 |
| `vehicle_instance_id` | str/int | 车辆实例 | $m$ |
| `vehicle_type_id` | str/int | 车型 | $k$ |
| `energy_type` | str | 能源类型 | 能耗函数参数 |
| `seq` | int | 路线内顺序 | 路径顺序 |
| `from_node`, `to_node` | int/str | 弧段起终点 | $(i,j)$ |
| `service_unit_id` | str | 服务单元编号 | 状态层 $u$ |
| `customer_id` | int/str | 客户编号 | 优化层 $j=c(u)$ |
| `depart_time` | time/min | 离开起点时刻 | 时间传播 |
| `arrival_time` | time/min | 到达客户时刻 | $t_{jm}$ |
| `service_start_time` | time/min | 开始服务时刻 | $S_{jm}$ |
| `service_end_time` | time/min | 服务结束时刻 | 冻结判断 |
| `weight_served`, `volume_served` | float | 本记录服务量 | 服务量追踪 |
| `wait_min`, `late_min` | float | 等待和迟到 | Q1 时间窗口径 |
| `leg_energy_cost`, `leg_carbon_cost` | float | 弧段能耗和碳成本 | 冻结成本 |

时间字段进入 Q3 前必须统一为绝对分钟，例如 `08:00 = 480`，`14:30 = 870`。

### 3.2 车辆输入

每个车辆实例至少需要：

| 字段 | 类型 | 含义 | 对应对象 |
|---|---|---|---|
| `vehicle_instance_id` | str/int | 车辆实例 | $m$ |
| `vehicle_type_id` | str/int | 车型 | $k$ |
| `energy_type` | str | 能源类型 | 能耗函数参数 |
| `capacity_weight` | float | 重量容量 | $Q_m^w$ |
| `capacity_volume` | float | 体积容量 | $Q_m^v$ |
| `startup_cost` | float | 固定启动成本 | $f_m$ |
| `available_count` | int | 车型可用数量 | $\text{available}_k$ |

### 3.3 服务单元与事件输入

服务单元表只用于状态层和聚合层：

| 字段 | 类型 | 含义 | 对应对象 |
|---|---|---|---|
| `service_unit_id` | str | 服务单元编号 | $u$ |
| `customer_id` | int/str | 对应客户 | $c(u)$ |
| `weight`, `volume` | float | 服务单元需求 | $W_u,V_u$ |
| `window_start_min`, `window_end_min` | float | 时间窗 | $e_u,l_u$ |
| `service_time_min` | float | 服务时长 | $s_u$ |
| `x_km`, `y_km` | float | 坐标 | 距离计算 |

事件表建议字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_id` | str | 事件编号 |
| `event_type` | str | `new_order`, `cancel_order`, `address_change`, `time_window_change` |
| `event_time_min` | float | 事件时刻 |
| `customer_id` | int/str | 受影响客户 |
| `service_unit_id` | str | 受影响服务单元，新单可用 `event_new_25` |
| `weight`, `volume` | float | 新增或变更需求 |
| `window_start_min`, `window_end_min` | float | 新时间窗 |
| `service_time_min` | float | 服务时长 |
| `x_km`, `y_km` | float | 新坐标 |

### 3.3.1 事件数学更新逻辑

事件表不是直接作为路径节点输入优化器，而是先更新服务单元状态。设事件时刻为 $t_r$，同一时刻的事件集合为：

$$
\mathcal E(t_r)=\{e\mid \texttt{event\_time\_min}(e)=t_r\}
$$

事件 $e$ 的类型记为 $\theta_e$，受影响服务单元为 $u_e$，受影响客户为 $j_e$。代码层应实现：

$$
\mathcal S(t_r^+)=
\Phi\left(\mathcal S(t_r^-),\mathcal E(t_r)\right)
$$

若同一时刻有多条事件，可按输入顺序或 `event_id` 顺序逐条应用：

$$
\mathcal S_e^+=\Phi_{\theta_e}(\mathcal S_e^-,e)
$$

事件更新只改变状态集合和服务单元参数，不产生路径决策变量。

#### 新增订单 `new_order`

新增订单先生成一个新的服务单元 $u_e$。若事件字段给出重量、体积、服务时间窗、服务时长和坐标，则：

$$
U^+ = U^-\cup\{u_e\}
$$

$$
U^{new,+}(t_r)=U^{new,-}(t_r)\cup\{u_e\}
$$

$$
c^+(u_e)=j_e,\qquad
W_{u_e}^+=\texttt{weight}_e,\qquad
V_{u_e}^+=\texttt{volume}_e
$$

$$
e_{u_e}^+=\texttt{window\_start\_min}_e,\qquad
l_{u_e}^+=\texttt{window\_end\_min}_e,\qquad
s_{u_e}^+=\texttt{service\_time\_min}_e
$$

若 $j_e$ 是新客户或事件显式给出新坐标，则：

$$
(x_{j_e}^+,y_{j_e}^+)=
(\texttt{x\_km}_e,\texttt{y\_km}_e)
$$

新增服务单元不可能已经在任何已离仓车辆上：

$$
u_e\notin U_m^{onboard}(t_r),\qquad \forall m\in M^{act}(t_r)
$$

因此已离仓车辆不能服务新增部分；新增部分只能由事件时刻在仓或未启动车辆承接。

#### 取消订单 `cancel_order`

取消只对未冻结服务单元生效。冻结集合为：

$$
U^{fix}(t_r)=U^{done}(t_r)\cup U^{cur}(t_r)
$$

若 $u_e\notin U^{fix}(t_r)$，则：

$$
U^{cancel,+}(t_r)=U^{cancel,-}(t_r)\cup\{u_e\}
$$

若 $u_e\in U^{fix}(t_r)$，则不回滚已执行事实，代码只在事件处理表中记录 `ignored_frozen` 或同类状态：

$$
U^{fix,+}(t_r)=U^{fix,-}(t_r)
$$

取消事件最终通过残余集合公式生效：

$$
u_e\in U^{cancel,+}(t_r)
\Rightarrow
u_e\notin U^{rem,+}(t_r)
$$

#### 地址变更 `address_change`

地址变更只更新未冻结、未取消服务单元对应客户的坐标。若：

$$
u_e\notin U^{fix}(t_r)\cup U^{cancel}(t_r)
$$

则对 $j_e=c(u_e)$ 更新：

$$
(x_{j_e}^+,y_{j_e}^+)=
(\texttt{x\_km}_e,\texttt{y\_km}_e)
$$

并重算与该客户相关的距离行列：

$$
d_{ij_e}^+=
\operatorname{dist}\left((x_i,y_i),(x_{j_e}^+,y_{j_e}^+)\right),
\qquad
\forall i\in \{0\}\cup N^{rem,+}(t_r)
$$

$$
d_{j_ei}^+=
\operatorname{dist}\left((x_{j_e}^+,y_{j_e}^+),(x_i,y_i)\right),
\qquad
\forall i\in \{0\}\cup N^{rem,+}(t_r)
$$

随后旅行时间和能耗成本使用更新后的 $d^+$：

$$
\tau_{ij_e}^+(t)=\tau(d_{ij_e}^+,t),\qquad
c_{ij_em}^{energy,+}=c^{energy}(d_{ij_e}^+,m,t)
$$

#### 时间窗调整 `time_window_change`

时间窗调整只更新未冻结、未取消服务单元。若：

$$
u_e\notin U^{fix}(t_r)\cup U^{cancel}(t_r)
$$

则：

$$
e_{u_e}^+=\texttt{window\_start\_min}_e,\qquad
l_{u_e}^+=\texttt{window\_end\_min}_e
$$

后续客户层聚合时间窗同步更新：

$$
e_{j}^{rem,+}=\max_{u\in U_j^{rem,+}(t_r)} e_u^+,\qquad
l_{j}^{rem,+}=\min_{u\in U_j^{rem,+}(t_r)} l_u^+
$$

等待和迟到变量不在事件处理阶段手工改值，而是在残余优化约束中按新的 $e_j^{rem,+},l_j^{rem,+}$ 重新计算。

#### 事件后残余集合统一重建

所有事件应用完后，统一重建残余服务单元和残余客户，不允许在原残余表上局部打补丁：

$$
U^{rem,+}(t_r)
=
\left[
\left(U\setminus U^{fix}(t_r)\right)
\cup U^{new,+}(t_r)
\right]
\setminus U^{cancel,+}(t_r)
$$

$$
U_j^{rem,+}(t_r)=
\{u\in U^{rem,+}(t_r)\mid c^+(u)=j\}
$$

$$
N^{rem,+}(t_r)=
\{j\mid U_j^{rem,+}(t_r)\ne\varnothing\}
$$

$$
W_j^{rem,+}=\sum_{u\in U_j^{rem,+}(t_r)}W_u^+,\qquad
V_j^{rem,+}=\sum_{u\in U_j^{rem,+}(t_r)}V_u^+
$$

$$
e_j^{rem,+}=\max_{u\in U_j^{rem,+}(t_r)}e_u^+,\qquad
l_j^{rem,+}=\min_{u\in U_j^{rem,+}(t_r)}l_u^+
$$

服务时长按当前执行口径生成：

$$
s_j^{rem,+}=
\begin{cases}
\sum_{u\in U_j^{rem,+}(t_r)}s_u^+, & \text{逐服务单元计时},\\
\max_{u\in U_j^{rem,+}(t_r)}s_u^+, & \text{同一客户一次到访计时}.
\end{cases}
$$

若出现 $e_j^{rem,+}>l_j^{rem,+}$，说明同一残余客户的多个服务单元时间窗交集为空。代码应将该客户标为软时间窗高风险或不可行候选，并在结果中输出原因；不得静默丢弃事件。

### 3.4 距离、速度与成本输入

Q3 沿用 Q1：

1. 距离矩阵或 `distance_long.csv`；
2. 时变速度函数；
3. 能耗与碳成本函数；
4. 等待成本与迟到惩罚单价；
5. 车型容量、可用数量和固定启动成本。

扰动指标只作为输出 KPI，不作为成本参数输入。

## 4. 时间与能耗计算函数

### 4.1 时间单位

代码内部统一使用绝对分钟：

```text
08:00 = 480
14:30 = 870
16:00 = 960
17:00 = 1020
```

若公式展示使用相对 `8:00` 的小时数，则：

$$
t^{hour}=\frac{t^{minute}-480}{60}
$$

### 4.2 时段速度函数

复用 Q1：

```text
speed_at(time_min) -> km_per_min
```

函数应覆盖 Q3 可能出现的所有残余执行时刻。若 `time_min < 480`，应报错或夹到规划起点，不能创建 8:00 前的执行分支。

### 4.3 分段累计旅行时间

复用 Q1：

```text
travel_time_min(from_node, to_node, depart_time_min, distance_km) -> travel_min
```

要求：

1. 从 `depart_time_min` 开始按时段速度逐段推进；
2. 跨路况时段时同步切分距离；
3. 返回旅行时间分钟数；
4. 能耗函数使用同一套时段切分结果。

### 4.4 能耗与碳成本函数

复用 Q1：

```text
energy_cost(vehicle, distance_segments, load_ratio) -> energy_cost
carbon_cost(vehicle, energy_amount) -> carbon_cost
```

Q3 只改变路线起点、出发时刻和载荷状态，不改变能耗公式。

## 5. 决策变量

Q3 有两类对象：状态对象和残余优化变量。状态对象由 Q1 执行表和事件表构造，不由优化器决策。

状态对象：

| 对象 | 代码字段 | 含义 |
|---|---|---|
| $U^{fix}(t_r)$ | `frozen_service_unit_ids` | 已完成或保守冻结服务单元 |
| $U^{rem}(t_r)$ | `residual_service_units` | 未冻结且仍需处理的服务单元 |
| $N^{rem}(t_r)$ | `residual_customers` | 残余客户集合 |
| $U_m^{onboard}(t_r)$ | `onboard_service_unit_ids` | 车辆 $m$ 车上已装载且尚未完成服务单元 |
| $N_m^{onboard}(t_r)$ | `onboard_customer_ids` | 由车上服务单元映射得到的客户 |
| $W_{jm}^{onboard},V_{jm}^{onboard}$ | `onboard_deliverable_weight/volume` | 车辆 $m$ 对客户 $j$ 的车上承诺货量 |
| $\bar\lambda_{jm}^{onboard}$ | `onboard_assignment_cap` | 已离仓可承担比例上界 |
| $o_m(t_r)$ | `current_node` | 车辆残余有效起点 |
| $t_m^{avail}(t_r)$ | `available_time_min` | 车辆可用时刻 |

残余优化变量按客户层定义：

| 数学变量 | 代码对象 | 类型 | 说明 |
|---|---|---|---|
| $x_{ijm}^{(r)}$ | `residual_route_arcs` | bool/int | 客户层残余弧 |
| $y_m^{(r)}$ | `vehicle_used_in_residual` | bool/int | 残余阶段是否使用车辆 |
| $\lambda_{jm}^{(r)}$ | `customer_assignment_fraction` | float | 车辆承担残余客户比例 |
| $q_{ijm}^{w,(r)}$ | `weight_load_after_depart` | float | 弧段重量载荷 |
| $q_{ijm}^{v,(r)}$ | `volume_load_after_depart` | float | 弧段体积载荷 |
| $t_{jm}^{(r)}$ | `arrival_time_min` | float | 到达客户时刻 |
| $S_{jm}^{(r)}$ | `service_start_time_min` | float | 服务开始时刻 |
| $D_{jm}^{(r)}$ | `depart_time_min` | float | 离开客户时刻 |
| $T_m^{ret,(r)}$ | `finish_time_min` | float | 最终返仓时刻 |
| $\varepsilon_{jm}^{+,(r)}$ | `wait_min` | float | 等待分钟 |
| $\varepsilon_{jm}^{-,(r)}$ | `late_min` | float | 迟到分钟 |
| $u_{jm}^{(r)}$ | `customer_visit_order` | float | 客户层 MTZ 顺序 |

禁止把 `service_unit_id` 建成路径节点、时间变量或 MTZ 顺序变量。

## 6. 目标函数

Q3 总成本：

$$
Z_3(t_r)=C_{\text{fix}}(t_r)+Z_{\text{rem}}(t_r)
$$

$C_{\text{fix}}(t_r)$ 是冻结前缀历史成本，由 Q1 路线执行表汇总，不参与残余优化。

残余主目标：

$$
\min Z_{\text{rem}}(t_r)
=
C_{\text{start}}^{(r)}
+C_{\text{energy}}^{(r)}
+C_{\text{carbon}}^{(r)}
+C_{\text{wait}}^{(r)}
+C_{\text{late}}^{(r)}
$$

其中各分项必须按下式计算：

$$
C_{\text{start}}^{(r)}
=
\sum_{m\in M^{act}(t_r)} f_m^{(r)}y_m^{(r)}
$$

$$
C_{\text{energy}}^{(r)}
=
\sum_{m\in M^{act}(t_r)}
\sum_{(i,j)\in A_m^{(r)}}
c_{ijm}^{energy,(r)}x_{ijm}^{(r)}
$$

$$
C_{\text{carbon}}^{(r)}
=
\sum_{m\in M^{act}(t_r)}
\sum_{(i,j)\in A_m^{(r)}}
c_{ijm}^{carbon,(r)}x_{ijm}^{(r)}
$$

$$
C_{\text{wait}}^{(r)}
=p^{wait}
\sum_{j\in N^{rem}(t_r)}
\sum_{m\in M^{act}(t_r)}
\varepsilon_{jm}^{+,(r)}
$$

$$
C_{\text{late}}^{(r)}
=p^{late}
\sum_{j\in N^{rem}(t_r)}
\sum_{m\in M^{act}(t_r)}
\varepsilon_{jm}^{-,(r)}
$$

残余固定启动成本：

$$
f_m^{(r)}=
\begin{cases}
0, & a_m(t_r)=1,\\
f_m, & a_m(t_r)=0.
\end{cases}
$$

在残余数学模型中，事件前已启动车辆残余阶段固定成本为 0，事件后新启动车辆计一次固定成本。若执行层将多条残余路线映射到同一物理 `vehicle_id` 或 `vehicle_instance_id`，最终 `fixed_cost` / `startup_cost` 必须按唯一物理车辆去重，不能按 `route_id` 累加，否则 Q3 总成本会重复计算固定成本。

扰动不进入目标函数，只作为 KPI 输出。

## 7. 约束

### 7.1 冻结前缀与残余聚合

冻结服务单元：

$$
U^{fix}(t_r)=U^{done}(t_r)\cup U^{cur}(t_r)
$$

残余服务单元：

$$
U^{rem}(t_r)=
\left[
\left(U\setminus U^{fix}(t_r)\right)
\cup U^{new}(t_r)
\right]
\setminus U^{cancel}(t_r)
$$

冻结服务单元不得重复进入残余：

$$
U^{fix}(t_r)\cap U^{rem}(t_r)=\varnothing
$$

残余客户：

$$
N^{rem}(t_r)=\{j\in N\mid \exists u\in U^{rem}(t_r),c(u)=j\}
$$

$$
U_j^{rem}(t_r)=\{u\in U^{rem}(t_r)\mid c(u)=j\}
$$

聚合字段：

$$
W_j^{rem}=\sum_{u\in U_j^{rem}(t_r)}W_u,\qquad
V_j^{rem}=\sum_{u\in U_j^{rem}(t_r)}V_u
$$

$$
e_j^{rem}=\max_{u\in U_j^{rem}(t_r)}e_u,\qquad
l_j^{rem}=\min_{u\in U_j^{rem}(t_r)}l_u
$$

### 7.2 残余需求满足与拆分

严格可行模型中：

$$
\sum_{m\in M^{act}(t_r)}\lambda_{jm}^{(r)}=1,
\qquad \forall j\in N^{rem}(t_r)
$$

访问联动：

$$
v_{jm}^{(r)}=\sum_{i\in V_m^{(r)},i\ne j}x_{ijm}^{(r)}
$$

$$
0\le \lambda_{jm}^{(r)}\le v_{jm}^{(r)}
$$

### 7.3 路径连续与车辆启用

残余节点集：

$$
V_m^{(r)}=\{o_m(t_r)\}\cup N^{rem}(t_r)\cup\{0\}
$$

残余弧集只包含不同节点之间的有向弧：

$$
A_m^{(r)}=\{(i,j)\mid i,j\in V_m^{(r)},\ i\ne j\}
$$

车辆从事件时刻有效起点出发：

$$
\sum_{j\in V_m^{(r)},j\ne o_m(t_r)}
x_{o_m(t_r),j,m}^{(r)}=y_m^{(r)}
$$

最终返仓：

$$
\sum_{i\in V_m^{(r)},i\ne 0}x_{i0m}^{(r)}=y_m^{(r)}
$$

客户节点流入流出平衡：

$$
\sum_{i\in V_m^{(r)},i\ne j}x_{ijm}^{(r)}
=
\sum_{k\in V_m^{(r)},k\ne j}x_{jkm}^{(r)}
\le 1
$$

车辆启用联动：

$$
v_{jm}^{(r)}\le y_m^{(r)},
\qquad
\forall j\in N^{rem}(t_r),\forall m\in M^{act}(t_r)
$$

车型可用数量约束：

$$
\sum_{m\in M_k}
\mathbb I\left(a_m(t_r)=1\ \text{or}\ y_m^{(r)}=1\right)
\le \text{available}_k,
\qquad \forall k\in K
$$

### 7.4 载荷流守恒

重量载荷：

$$
\sum_{i\in V_m^{(r)},i\ne j}q_{ijm}^{w,(r)}
-
\sum_{k\in V_m^{(r)},k\ne j}q_{jkm}^{w,(r)}
=\lambda_{jm}^{(r)}W_j^{rem}
$$

体积载荷：

$$
\sum_{i\in V_m^{(r)},i\ne j}q_{ijm}^{v,(r)}
-
\sum_{k\in V_m^{(r)},k\ne j}q_{jkm}^{v,(r)}
=\lambda_{jm}^{(r)}V_j^{rem}
$$

最终返仓弧必须空载：

$$
\sum_{i\in V_m^{(r)},i\ne 0}
q_{i0m}^{w,(r)}=0,\qquad
\sum_{i\in V_m^{(r)},i\ne 0}
q_{i0m}^{v,(r)}=0
$$

### 7.5 容量与车上货物

容量上界：

$$
B_m^w(t_r)=
\begin{cases}
Q_m^w, & \chi_m^0(t_r)=1,\\
b_m^w(t_r), & \chi_m^0(t_r)=0.
\end{cases}
$$

体积上界为：

$$
B_m^v(t_r)=
\begin{cases}
Q_m^v, & \chi_m^0(t_r)=1,\\
b_m^v(t_r), & \chi_m^0(t_r)=0.
\end{cases}
$$

每条被使用残余弧的载荷不得超过该车残余载荷上界，未使用弧载荷必须为 0：

$$
0\le q_{ijm}^{w,(r)}
\le B_m^w(t_r)x_{ijm}^{(r)},\qquad
0\le q_{ijm}^{v,(r)}
\le B_m^v(t_r)x_{ijm}^{(r)}
$$

$$
\forall (i,j)\in A_m^{(r)},\forall m\in M^{act}(t_r)
$$

已离仓车辆只能服务车上服务单元对应的残余比例：

$$
W_{jm}^{onboard}(t_r)
=
\sum_{u\in U_m^{onboard}(t_r)\cap U_j^{rem}(t_r)}W_u,\qquad
V_{jm}^{onboard}(t_r)
=
\sum_{u\in U_m^{onboard}(t_r)\cap U_j^{rem}(t_r)}V_u
$$

$$
\bar\lambda_{jm}^{onboard}(t_r)
=
\min\left\{
\frac{W_{jm}^{onboard}(t_r)}{W_j^{rem}},
\frac{V_{jm}^{onboard}(t_r)}{V_j^{rem}}
\right\}
$$

$$
\lambda_{jm}^{(r)}
\le
\bar\lambda_{jm}^{onboard}(t_r)
+\chi_m^0(t_r)
$$

当 $\chi_m^0(t_r)=0$ 时，若 $\bar\lambda_{jm}^{onboard}(t_r)=0$，则该候选不可行；若同一客户同时有车上旧货和新增服务单元，候选最多只能承担车上旧货对应比例。

### 7.6 时间传播与返仓

残余首弧：

$$
t_{jm}^{(r)}
\ge
t_m^{avail}(t_r)
+\tau_{o_m(t_r),j}(t_m^{avail}(t_r))
-\Omega(1-x_{o_m(t_r),j,m}^{(r)})
$$

$$
t_{jm}^{(r)}
\le
t_m^{avail}(t_r)
+\tau_{o_m(t_r),j}(t_m^{avail}(t_r))
+\Omega(1-x_{o_m(t_r),j,m}^{(r)})
$$

$$
\forall j\in N^{rem}(t_r),\forall m\in M^{act}(t_r)
$$

若车辆事件时刻在仓或尚未启动，则 `current_node = depot`；若车辆已离仓，则从有效位置继续配送车上承诺货物。Q3 数学主模型不设置中途补货字段，也不刻画同一物理车辆的多趟复用；车辆 $m$ 只表示残余优化中的一次路线执行。执行层若允许车辆返仓后复用，应在路线排程和结果统计中单独说明，并校验同一物理车辆的多条执行路线时间不重叠、固定成本按唯一物理车辆去重。

客户间传播：

$$
t_{km}^{(r)}
\ge
D_{jm}^{(r)}
+\tau_{jk}(D_{jm}^{(r)})
-\Omega(1-x_{jkm}^{(r)})
$$

$$
t_{km}^{(r)}
\le
D_{jm}^{(r)}
+\tau_{jk}(D_{jm}^{(r)})
+\Omega(1-x_{jkm}^{(r)})
$$

$$
\forall j,k\in N^{rem}(t_r),j\ne k,\forall m\in M^{act}(t_r)
$$

服务开始与离开客户：

$$
S_{jm}^{(r)}\ge t_{jm}^{(r)},\qquad
S_{jm}^{(r)}\ge e_j^{rem}-\Omega(1-v_{jm}^{(r)})
$$

$$
S_{jm}^{(r)}
\le
t_{jm}^{(r)}+\varepsilon_{jm}^{+,(r)}
+\Omega(1-v_{jm}^{(r)})
$$

$$
D_{jm}^{(r)}
\ge
S_{jm}^{(r)}+s_j^{rem}
-\Omega(1-v_{jm}^{(r)})
$$

$$
D_{jm}^{(r)}
\le
S_{jm}^{(r)}+s_j^{rem}
+\Omega(1-v_{jm}^{(r)})
$$

$$
\forall j\in N^{rem}(t_r),\forall m\in M^{act}(t_r)
$$

最终返仓时刻：

$$
T_m^{ret,(r)}
\ge
D_{jm}^{(r)}
+\tau_{j0}(D_{jm}^{(r)})
-\Omega(1-x_{j0m}^{(r)})
$$

$$
T_m^{ret,(r)}
\le
D_{jm}^{(r)}
+\tau_{j0}(D_{jm}^{(r)})
+\Omega(1-x_{j0m}^{(r)})
$$

$$
\forall j\in N^{rem}(t_r),\forall m\in M^{act}(t_r)
$$

未启用车辆的最终返仓时刻归零：

$$
0\le T_m^{ret,(r)}\le \Omega y_m^{(r)},
\qquad \forall m\in M^{act}(t_r)
$$

### 7.7 软时间窗

若 Q1 以到达时刻判定迟到：

$$
\varepsilon_{jm}^{+,(r)}
\ge e_j^{rem}-t_{jm}^{(r)}-\Omega(1-v_{jm}^{(r)})
$$

$$
\varepsilon_{jm}^{-,(r)}
\ge t_{jm}^{(r)}-l_j^{rem}-\Omega(1-v_{jm}^{(r)})
$$

若 Q1 以服务开始时刻判定迟到，则将第二式中的 $t_{jm}^{(r)}$ 替换为 $S_{jm}^{(r)}$。

未访问客户的时间变量和时间窗偏差变量归零，避免输出表出现未访问客户的虚假时刻：

$$
0\le t_{jm}^{(r)},S_{jm}^{(r)},D_{jm}^{(r)},
\varepsilon_{jm}^{+,(r)},\varepsilon_{jm}^{-,(r)}
\le \Omega v_{jm}^{(r)}
$$

$$
\forall j\in N^{rem}(t_r),\forall m\in M^{act}(t_r)
$$

### 7.8 子回路消除

客户层 MTZ：

$$
0\le u_{jm}^{(r)}
\le |N^{rem}(t_r)|v_{jm}^{(r)}
$$

$$
u_{jm}^{(r)}-u_{km}^{(r)}
+|N^{rem}(t_r)|x_{jkm}^{(r)}
\le |N^{rem}(t_r)|-1
$$

### 7.9 变量域

$$
x_{ijm}^{(r)},y_m^{(r)}\in\{0,1\},\qquad
0\le \lambda_{jm}^{(r)}\le 1
$$

$$
q_{ijm}^{w,(r)},q_{ijm}^{v,(r)},t_{jm}^{(r)},S_{jm}^{(r)},
D_{jm}^{(r)},T_m^{ret,(r)},
\varepsilon_{jm}^{+,(r)},\varepsilon_{jm}^{-,(r)},u_{jm}^{(r)}\ge 0
$$

## 8. 大致计算思路

### 8.1 数据准备

1. 读取 Q1 路线表、车辆表、服务单元表、事件表和距离矩阵。
2. 将所有时间字段统一为绝对分钟。
3. 校验事件时刻不早于 `08:00`。
4. 校验车辆实例数不超过车型可用数量。
5. 不读取 Q2 政策路径，不调用 GAC 检查。

### 8.2 状态切片

构造冻结记录：

```text
frozen_done_rows = rows where service_end_time_min <= event_time_min
frozen_current_rows = rows in active service or incoming arc at event_time_min
frozen_rows = frozen_done_rows + frozen_current_rows
frozen_service_unit_ids = frozen_rows.service_unit_id
```

构造车辆状态：

```text
current_node
available_time_min
started_before_event
residual_startup_cost
onboard_service_unit_ids
onboard_customer_ids
onboard_assignment_cap
onboard_weight_remaining
onboard_volume_remaining
```

`onboard_service_unit_ids` 是物理口径的车上货物集合，`onboard_customer_ids` 仅由它映射得到。`onboard_service_unit_ids` 只能来自事件时刻该物理车辆正在执行的当前 `route_id` 中，已经离仓且尚未服务完成的服务单元；若同一 `vehicle_id` 或 `vehicle_instance_id` 在事件时刻之后还存在尚未出发的后续路线，这些后续路线中的服务单元不得计入 `onboard_service_unit_ids`，只能作为残余任务重新优化或作为执行层后续排程对象。若数据没有显式装载记录，可由 Q1 原计划中该车当前执行路线内事件后仍承诺配送的服务单元聚合推断，并在结果说明中声明。`onboard_assignment_cap[(vehicle, customer)]` 对应 $\bar\lambda_{jm}^{onboard}(t_r)$，用于避免同一客户的新增服务单元被已离仓车辆误服务。

### 8.3 残余服务单元聚合

```text
event_state = apply_events_in_order(original_service_units, event_rows)
candidate_service_units = original_service_units
candidate_service_units -= frozen_service_unit_ids
candidate_service_units += event_state.new_event_service_units
candidate_service_units -= event_state.cancelled_service_unit_ids
remaining_service_units = apply_updated_parameters(candidate_service_units, event_state)
```

聚合接口：

```text
aggregate_residual_customers(remaining_service_units)
    -> residual_customers, unit_customer_map
```

`residual_customers` 至少包含：

| 字段 | 含义 |
|---|---|
| `customer_id` | 残余客户 $j$ |
| `residual_weight`, `residual_volume` | $W_j^{rem},V_j^{rem}$ |
| `window_start_min`, `window_end_min` | $e_j^{rem},l_j^{rem}$ |
| `service_time_min` | $s_j^{rem}$ |
| `source_service_unit_ids` | 来源服务单元列表 |

优化器只读取 `residual_customers` 作为待服务节点。

### 8.4 启发式求解接口

建议接口：

```text
build_residual_plan(
    residual_customers,
    unit_customer_map,
    vehicle_states,
    vehicles,
    distance,
    event_time_min,
    old_remaining_plan,
    scenario_name="q3_dynamic_event"
)
```

候选路线评价顺序：

1. 读取车辆 `current_node` 和 `available_time_min`。
2. 读取目标客户的 `onboard_assignment_cap`。
3. 若车辆不在仓且该上限不足以覆盖候选服务比例，则该候选在数学主模型中不可行。
4. 若车辆在仓或尚未启动，从仓库出发；否则从 `current_node` 出发。
5. 从正确起点计算时变旅行时间、到达、等待、服务和离开时刻。
6. 检查重量、体积、路径连续和最终返仓。
7. 计算能耗、碳成本、等待成本和迟到成本。
8. 计算扰动 KPI。

### 8.5 扰动指标

原计划残余客户集合：

$$
N^{old,rem}(t_r)
=
\{c(u)\mid u\in (U\setminus U^{fix}(t_r))\setminus U^{cancel}(t_r)\}
$$

比较弧集合：

$$
A_m^{cmp}(t_r)
=
\{(i,j)\mid i,j\in \{o_m(t_r),0\}\cup N^{old,rem}(t_r),\ i\ne j\}
$$

$$
A^{cmp}(t_r)=\bigcup_{m\in M^{act}(t_r)}A_m^{cmp}(t_r)
$$

新增客户和新增订单相关弧不进入 $A_m^{cmp}(t_r)$。

实现步骤：

1. 从 `old_remaining_plan` 生成 `old_remaining_arc_used[(vehicle, i, j)]`。
2. 从新方案生成 `new_arc_used[(vehicle, i, j)]`。
3. 构造 `comparison_arcs[vehicle] = A_m^{cmp}(t_r)`，只包含原计划残余客户、车辆有效起点和仓库。
4. 遍历 `comparison_arcs`，缺失键按 0 处理，累加 `abs(new_arc_used - old_remaining_arc_used)`。
5. 新增客户相关弧不在 `comparison_arcs` 中，因此不会增加 `changed_arc_count`。

```text
changed_arc_count =
    sum over vehicle m and arcs in A_m_cmp:
        abs(new_arc_used - old_remaining_arc_used)
```

弧变化是“结构差异”计数。旧弧被删掉记 1，新弧被插入记 1，保持不变记 0。一次改道可能同时产生多条删除弧和插入弧。

```text
reassigned_customer_count =
    count old residual customers whose serving vehicle set changed
```

车辆重分配按客户集合比较：

```text
old_vehicle_set[j] = vehicles serving customer j in old_remaining_plan
new_vehicle_set[j] = vehicles with customer_assignment_fraction[j, vehicle] > 0
reassigned_customer_count =
    count j in old_residual_customers
    where old_vehicle_set[j] != new_vehicle_set[j]
```

如果客户从单车服务变为拆分配送，或拆分车辆集合发生变化，都只对该客户记 1 次；新增客户不进入 `old_residual_customers`，所以不参与该计数。

综合扰动代理：

$$
I^{disrupt}(t_r)
=
\frac{\Delta^{arc}(t_r)}{\max(1,|A^{cmp}(t_r)|)}
+
\frac{\Delta^{assign}(t_r)}{\max(1,|N^{old,rem}(t_r)|)}
$$

`question3_dynamic_cases.json` 中 `disruption_proxy` 可以直接写数值，也可以写结构体：

```text
disruption_proxy = {
    "changed_arc_count": ...,
    "reassigned_customer_count": ...,
    "value": I_disrupt
}
```

推荐直接输出结构体，便于论文同时解释原始计数和归一化值。若只需要一个数值，取 `value`。由于两个分母使用 `max(1, size)`，没有原计划残余客户时不会除零；正常情况下 `value` 位于 `[0, 2]`，越大表示对原计划后缀改动越大。

### 8.6 输出字段

`q3_route_plan.csv` 至少包含：

| 字段 | 说明 |
|---|---|
| `phase` | `frozen_prefix` 或 `residual_reopt` |
| `vehicle_instance_id` | 车辆实例 |
| `seq` | 路线顺序 |
| `from_node`, `to_node` | 客户层弧段 |
| `customer_id` | 残余优化节点 |
| `service_unit_id` | 追踪字段，可为来源服务单元列表或冻结记录原值 |
| `arrival_time`, `service_start_time`, `service_end_time` | 时间字段 |
| `weight_served`, `volume_served` | 客户层服务量 |

`question3_dynamic_cases.json` 至少包含：

| 字段 | 含义 |
|---|---|
| `q3_method` | `event_driven_rolling_reoptimization` |
| `event_time` | 事件时刻 |
| `event_units` | 事件服务单元 |
| `frozen_service_units` | 冻结服务单元 |
| `residual_service_units` | 残余服务单元 |
| `residual_customers` | 残余客户集合 $N^{rem}(t_r)$ |
| `unit_customer_map` | 服务单元到残余客户映射 |
| `onboard_service_unit_sets` | 各车 $U_m^{onboard}(t_r)$ |
| `onboard_customer_sets` | 各车 $N_m^{onboard}(t_r)$ |
| `onboard_assignment_caps` | 各车对各残余客户的 $\bar\lambda_{jm}^{onboard}(t_r)$ |
| `route_count` | 残余输出路线条数 |
| `used_vehicle_count` | 实际启用车辆数，按唯一车辆实例去重 |
| `delta_route_count` | 相对 Q1 原计划后缀的路线条数变化 |
| `delta_used_vehicle_count` | 相对 Q1 原计划后缀的启用车辆数变化 |
| `fixed_cost` / `startup_cost` | 固定启动成本，执行层车辆复用时按唯一物理车辆去重 |
| `changed_arc_count` | $\Delta^{arc}$ |
| `reassigned_customer_count` | $\Delta^{assign}$ |
| `disruption_proxy` | $I^{disrupt}$ 或包含该值的结构体 |
| `frozen_duplicate_count` | 必须为 0 |



## 9. 一致性校验

实现完成后至少检查：

1. Q3 读取 Q1 执行状态，不默认读取 Q2 政策路径。
2. 冻结服务单元不在残余服务单元中重复出现。
3. 残余优化输入是 `residual_customers`，不是原始 `service_unit_id` 列表。
4. 新增 `event_new_25` 先进入事件服务单元，再并入客户 25 的残余客户需求。
5. 已离仓车辆没有超过 `onboard_assignment_cap` 服务残余客户；同一客户的新增服务单元不能被已离仓车辆凭客户号误服务。
6. Q3 数学主模型不生成中途补货字段或中途补货弧；车辆返仓后复用只能作为执行层排程修复另行说明。
7. `finish_time_min` 只表示最终返仓时刻。
8. 扰动弧只在 $A_m^{cmp}(t_r)$ 上统计。
9. 车辆重分配按客户统计为 `reassigned_customer_count`。
10. 扰动指标不参与总成本计算。
11. 不调用 Q2 绿色准入检查。
12. `onboard_service_unit_ids` 只能来自事件时刻该物理车辆正在执行的当前路线，不得把同一车辆未来尚未出发路线中的服务单元算作车上货物。
13. 若执行层采用车辆复用后处理，必须校验同一 `vehicle_id` 或 `vehicle_instance_id` 下所有路线时间区间不重叠；若出现重叠，则该 Q3 执行方案不可行，不能只在报告中提示。
14. 若执行层将多条残余路线映射到同一物理车辆，`fixed_cost` / `startup_cost` 必须按唯一物理车辆去重，不能按 `route_id` 累加。
15. 每个访问客户必须满足 `visit_flag <= vehicle_used_in_residual`，不能出现未启用车辆服务客户。
16. 每条残余弧必须满足 `0 <= load <= residual_load_upper_bound * arc_used`，返仓弧载荷必须为 0。
17. 事件前已启动和事件后新启用的车辆实例合计不得超过对应车型可用数量。
