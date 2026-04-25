# Q1 TDSDHVRPTW 编程手版本

对应源文件：

`/home/hanchen/华中杯A题（稳健codex）/analysis/q1_tdsdhvrptw_model_for_teammate.md`

本文件只服务代码实现，保留纯数理模型、变量接口、计算函数和大致求解流程。模型范围、假设、符号、目标函数和约束与源文件严格一致：仅覆盖 Q1 静态配送，不包含 Q2 绿色准入约束和 Q3 动态事件重优化。

## 1. 模型范围

Q1 主模型为：

$$
\text{TDSDHVRPTW}
$$

即时间依赖、允许拆分配送、异构车队、带时间窗车辆路径问题。

求解目标：决定车辆启用、客户服务比例、车辆访问顺序、到达时刻和弧段载荷，使总成本最小。

总成本由五项构成：

$$
Z_1=C_{start}+C_{energy}+C_{carbon}+C_{wait}+C_{late}
$$

## 2. 建模假设

| 编号 | 假设内容 | 实现含义 |
|---|---|---|
| A1 | 研究对象为单日配送计划，所有车辆从唯一配送中心 `0` 出发并最终返仓 | 路径均为 `0 -> customers -> 0` |
| A2 | 仅正需求客户进入 `Q1` 主模型，订单已在清洗阶段聚合到客户层 | 代码只为 $N^+$ 构造服务约束 |
| A3 | 所有时间变量统一采用相对 `8:00` 的小时数表示 | `16:00` 写作 $t=8$ |
| A4 | 时段随机车速采用题面给定分布的均值确定化，超出显式时段后按中速外推 | 用确定性函数 `v(t)` 计算旅行时间和能耗 |
| A5 | 允许拆分配送，同一客户可由多辆车共同完成 | 用 $\lambda_{jm}$ 表示车辆承担比例 |
| A6 | 重量容量和体积容量同时约束车辆可行性 | 同时检查 $Q_m^w,Q_m^v$ |
| A7 | 能耗修正由重量装载率驱动 | 用 $\rho_{ijm}=q_{ijm}^w/Q_m^w$ |
| A8 | 不考虑途中加油、充电和补能设施选址，数学主模型按单趟单回路刻画 | 车辆实例复用属于启发式执行层，不作为严格主模型设定 |

## 3. 输入接口

### 3.1 客户输入

每个正需求客户 $j\in N^+$ 需要字段：

| 字段 | 模型符号 | 单位 | 说明 |
|---|---|---|---|
| `customer_id` | $j$ | - | 客户编号 |
| `demand_weight` | $W_j$ | kg | 客户聚合重量需求 |
| `demand_volume` | $V_j$ | m$^3$ | 客户聚合体积需求 |
| `window_start` | $e_j$ | h | 相对 8:00 的最早服务时间 |
| `window_end` | $l_j$ | h | 相对 8:00 的最晚服务时间 |
| `service_time` | $s_j$ | h | 服务时间，当前取 $1/3$ |

只让正需求客户进入主模型：

$$
N^+=\{j\in N\mid W_j>0\ \text{or}\ V_j>0\}
$$

当前数据口径下 $|N^+|=88$。

### 3.2 车辆输入

每个车辆实例 $m\in M$ 需要字段：

| 字段 | 模型符号 | 单位 | 说明 |
|---|---|---|---|
| `vehicle_id` | $m$ | - | 车辆实例编号 |
| `vehicle_type` | $\kappa(m)$ | - | 车型编号 |
| `energy_type` | $e(m)$ | - | 燃油或新能源 |
| `weight_capacity` | $Q_m^w$ | kg | 最大载重 |
| `volume_capacity` | $Q_m^v$ | m$^3$ | 最大容积 |
| `fixed_cost` | $f_m$ | 元 | 固定启用成本 |

车辆集合按能源类型拆分：

$$
M=M^{fuel}\cup M^{elec},\qquad
M^{fuel}\cap M^{elec}=\varnothing
$$

### 3.3 距离输入

距离矩阵提供：

$$
d_{ij},\qquad (i,j)\in A
$$

其中：

$$
V=\{0\}\cup N^+,\qquad
A=\{(i,j)\mid i,j\in V,\ i\neq j\}
$$

## 4. 时间与能耗计算函数

### 4.1 时间单位

所有时间变量使用相对 `8:00` 的小时数：

$$
8:00=0,\qquad 16:00=8,\qquad 17:00=9
$$

### 4.2 时段速度函数

$$
v(t)=
\begin{cases}
9.8, & t\in[0,1)\cup[3.5,5)\\
55.3, & t\in[1,2)\cup[5,7)\\
35.4, & t\in[2,3.5)\cup[7,9)\\
35.4, & t\in[9,+\infty)
\end{cases}
$$

### 4.3 分段累计旅行时间

数学定义：

$$
\tau_{ij}(t)=
\inf\left\{\Delta\ge 0:\int_t^{t+\Delta}v(u)\,du\ge d_{ij}\right\}
$$

实现思路：

1. 初始化剩余距离 $r=d_{ij}$，当前时刻 $\theta=t$，累计时间 $g=0$。
2. 找到 $\theta$ 所在时段，速度为 $\bar v_{P(\theta)}$。
3. 计算当前时段最多可行驶距离：

$$
\Delta d=\bar v_{P(\theta)}[b(\theta)-\theta]
$$

4. 若 $r\le \Delta d$，则：

$$
g\leftarrow g+\frac{r}{\bar v_{P(\theta)}}
$$

输出 $\tau_{ij}(t)=g$。

5. 若 $r>\Delta d$，则：

$$
r\leftarrow r-\Delta d,\quad
g\leftarrow g+b(\theta)-\theta,\quad
\theta\leftarrow b(\theta)
$$

继续进入下一时段。

实现该函数时，同时记录每个时段完成的距离份额 $d_{ij}^{(p)}(t)$，用于能耗计算。

### 4.4 能耗函数

燃油车：

$$
FPK(v)=0.0025v^2-0.2554v+31.75
$$

新能源车：

$$
EPK(v)=0.0014v^2-0.12v+36.19
$$

装载率：

$$
\rho_{ijm}=\frac{q_{ijm}^w}{Q_m^w}
$$

装载修正：

$$
\phi^{fuel}(\rho)=1+0.4\rho,\qquad
\phi^{new}(\rho)=1+0.35\rho
$$

弧段能耗：

$$
E_{ijm}(D_{im},\rho_{ijm})=
\begin{cases}
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}FPK(\bar v_p)\phi^{fuel}(\rho_{ijm}), & m\in M^{fuel}\\
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}EPK(\bar v_p)\phi^{new}(\rho_{ijm}), & m\in M^{elec}
\end{cases}
$$

能源成本：

$$
c_{ijm}^{energy}=E_{ijm}(D_{im},\rho_{ijm})p_m^{energy}
$$

碳排放量：

$$
Q_{ijm}^{CO_2}=E_{ijm}(D_{im},\rho_{ijm})\eta_m^{CO_2}
$$

碳成本：

$$
c_{ijm}^{carbon}=Q_{ijm}^{CO_2}\pi^{CO_2}
=E_{ijm}(D_{im},\rho_{ijm})p_m^{carbon}
$$

## 5. 决策变量

| 变量 | 类型 | 含义 |
|---|---|---|
| $x_{ijm}$ | binary | 车辆 $m$ 是否走弧 $(i,j)$ |
| $y_m$ | binary | 车辆 $m$ 是否启用 |
| $\lambda_{jm}$ | continuous | 车辆 $m$ 承担客户 $j$ 的需求比例 |
| $q_{ijm}^w,q_{ijm}^v$ | continuous | 弧 $(i,j)$ 上的剩余重量和体积载荷 |
| $t_{jm}$ | continuous | 车辆 $m$ 到达客户 $j$ 的时刻 |
| $D_{im}$ | continuous | 车辆 $m$ 离开节点 $i$ 的时刻 |
| $T_m^{ret}$ | continuous | 车辆 $m$ 返回配送中心的时刻 |
| $\varepsilon_{jm}^+,\varepsilon_{jm}^-$ | continuous | 等待量和迟到量 |
| $u_{jm}$ | continuous | MTZ 路径序号变量 |

派生访问变量：

$$
v_{jm}=\sum_{i\in V,i\neq j}x_{ijm}
$$

配送量：

$$
\delta_{jm}^w=\lambda_{jm}W_j,\qquad
\delta_{jm}^v=\lambda_{jm}V_j
$$

## 6. 目标函数

$$
\min Z_1
=
\sum_{m\in M}f_my_m
+\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{energy}x_{ijm}
+\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{carbon}x_{ijm}
+p^{wait}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^+
+p^{late}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^-
$$

注意：$c_{ijm}^{energy}$ 和 $c_{ijm}^{carbon}$ 依赖 $D_{im}$ 和 $q_{ijm}^w$。原始模型不是严格线性 MILP，而是带时变旅行时间与载荷依赖成本的混合整数非线性车辆路径模型；代码中应采用查表、分段近似或启发式实时计算。

## 7. 约束

### 7.1 需求满足与拆分

$$
\sum_{m\in M}\lambda_{jm}=1,\qquad \forall j\in N^+
$$

$$
v_{jm}=\sum_{i\in V,i\neq j}x_{ijm},\qquad
0\le \lambda_{jm}\le v_{jm},\qquad
\forall j\in N^+,\forall m\in M
$$

### 7.2 路径连续与车辆启用

$$
\sum_{i\in V,i\neq j}x_{ijm}
=
\sum_{l\in V,l\neq j}x_{jlm}
\le 1,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{j\in N^+}x_{0jm}=y_m,\qquad
\sum_{i\in N^+}x_{i0m}=y_m,\qquad \forall m\in M
$$

$$
v_{jm}\le y_m,\qquad \forall j\in N^+,\forall m\in M
$$

### 7.3 载荷流守恒

$$
\sum_{i\in V,i\neq j}q_{ijm}^w
-
\sum_{l\in V,l\neq j}q_{jlm}^w
=
\lambda_{jm}W_j,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{i\in V,i\neq j}q_{ijm}^v
-
\sum_{l\in V,l\neq j}q_{jlm}^v
=
\lambda_{jm}V_j,\qquad \forall j\in N^+,\forall m\in M
$$

出仓载荷：

$$
\sum_{j\in N^+}q_{0jm}^w
=
\sum_{j\in N^+}\lambda_{jm}W_j,\qquad
\sum_{j\in N^+}q_{0jm}^v
=
\sum_{j\in N^+}\lambda_{jm}V_j,\qquad \forall m\in M
$$

返仓空载：

$$
\sum_{i\in N^+}q_{i0m}^w=0,\qquad
\sum_{i\in N^+}q_{i0m}^v=0,\qquad \forall m\in M
$$

### 7.4 容量

$$
0\le q_{ijm}^w\le Q_m^wx_{ijm},\qquad
0\le q_{ijm}^v\le Q_m^vx_{ijm},\qquad
\forall (i,j)\in A,\forall m\in M
$$

### 7.5 时间传播

$$
D_{jm}=t_{jm}+\varepsilon_{jm}^+ +s_jv_{jm},\qquad
\forall j\in N^+,\forall m\in M
$$

$$
D_{0m}=0,\qquad \forall m\in M
$$

$$
t_{jm}\ge \tau_{0j}(0)-\Omega(1-x_{0jm}),\qquad
\forall j\in N^+,\forall m\in M
$$

$$
t_{jm}\ge D_{im}+\tau_{ij}(D_{im})-\Omega(1-x_{ijm}),\qquad
\forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

返仓时刻：

$$
T_m^{ret}\ge D_{im}+\tau_{i0}(D_{im})-\Omega(1-x_{i0m}),\qquad
\forall i\in N^+,\forall m\in M
$$

$$
T_m^{ret}\le D_{im}+\tau_{i0}(D_{im})+\Omega(1-x_{i0m}),\qquad
\forall i\in N^+,\forall m\in M
$$

$$
T_m^{ret}\le T y_m,\qquad \forall m\in M
$$

### 7.6 软时间窗

$$
\varepsilon_{jm}^+\ge e_j-t_{jm}-\Omega(1-v_{jm}),\qquad
\forall j\in N^+,\forall m\in M
$$

$$
\varepsilon_{jm}^-\ge t_{jm}-l_j-\Omega(1-v_{jm}),\qquad
\forall j\in N^+,\forall m\in M
$$

关闭未访问节点时间变量：

$$
t_{jm},D_{jm},\varepsilon_{jm}^+,\varepsilon_{jm}^-\le \Omega v_{jm},\qquad
\forall j\in N^+,\forall m\in M
$$

### 7.7 子回路消除

$$
0\le u_{jm}\le n^+v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
u_{im}-u_{jm}+n^+x_{ijm}\le n^+-1,\qquad
\forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

### 7.8 变量域

$$
x_{ijm},y_m\in\{0,1\},\qquad
0\le\lambda_{jm}\le 1
$$

$$
q_{ijm}^w,q_{ijm}^v,t_{jm},D_{jm},T_m^{ret},
\varepsilon_{jm}^+,\varepsilon_{jm}^-,u_{jm}\ge 0
$$

## 8. 大致计算思路

### 8.1 数据准备

1. 读取正需求客户，构造 $N^+$。
2. 展开车辆实例集合 $M$，并标记 $M^{fuel},M^{elec}$。
3. 读取距离矩阵，构造有向弧集合 $A$。
4. 将时间窗统一转为相对 `8:00` 的小时数。

### 8.2 预计算函数

1. 对给定出发时刻 $t$，用分段推进算法计算 $\tau_{ij}(t)$。
2. 同时得到 $d_{ij}^{(p)}(t)$。
3. 按能源类型、速度时段和装载率计算 $E_{ijm}$。

若启发式中出发时刻连续变化，可按需实时计算；若使用离散近似，可对一组候选时刻预计算查表。

### 8.3 启发式求解接口

源模型在客户层使用 $\lambda_{jm}$ 连续拆分。代码实现可以构造 `service_unit` 作为离散任务块，但 `service_unit` 只属于求解器执行层，不改变数学模型；求解后应能聚合回客户层服务比例 $\lambda_{jm}$、服务重量 $\delta_{jm}^w$ 和服务体积 $\delta_{jm}^v$。

执行层建议流程：

1. 将客户需求按车辆容量或算法粒度离散为可执行服务单元；超单车容量客户必须拆分，普通客户可保留为一个服务单元。
2. 构造初始路线。
3. 对每条路线按访问顺序传播时间：
   $$t_{jm}=D_{im}+\tau_{ij}(D_{im})$$
4. 计算等待、迟到、能耗、碳成本和固定成本。
5. 检查容量、服务完成、时间窗、路径连续和返仓。
6. 输出路线表、客户服务表和 KPI。

### 8.4 输出字段

输出字段必须能回到模型变量或派生量。字段名可按代码习惯调整，但每个字段都必须有明确的计算或生成规则。索引类字段不属于数值计算，但必须说明由哪个集合、弧或路线枚举生成。

路线弧段表至少包含：

| 输出字段 | 计算或生成方式 | 对应模型对象 | 备注 |
|---|---|---|---|
| `vehicle_id` | 对每个满足 $y_m=1$ 的车辆输出其编号 $m$ | $m$ | 索引字段 |
| `route_id` | 按启用车辆或执行层路线枚举生成；严格主模型中每辆车只有一条回路，可令 `route_id` 等于车辆路线序号 | 派生编号 | 不是数学决策变量 |
| `sequence` | 从配送中心出发沿 $x_{ijm}=1$ 的弧依次递增编号；客户节点顺序应与 $u_{jm}$ 一致 | $u_{jm}$ 或访问顺序 | 执行层可直接按路线顺序生成 |
| `from_node` | 对每条被使用弧 $(i,j)$ 输出起点 $i$ | $i$ | 仅输出 $x_{ijm}=1$ 的弧 |
| `to_node` | 对每条被使用弧 $(i,j)$ 输出终点 $j$ | $j$ | 若 $j=0$，表示返仓弧 |
| `arc_used` | 取 $x_{ijm}$；路线表通常只保留 $x_{ijm}=1$ 的弧 | $x_{ijm}$ | 决策变量 |
| `distance_km` | 查距离矩阵得到 $d_{ij}$ | $d_{ij}$ | 参数 |
| `depart_time` | 若 $i=0$，取 $D_{0m}=0$；若 $i\in N^+$，取 $D_{im}$ | $D_{im}$ | 弧段离开时刻 |
| `arrival_time` | 若 $j\in N^+$，取 $t_{jm}$；若 $j=0$，取 $T_m^{ret}$ | $t_{jm}$ 或 $T_m^{ret}$ | 返仓弧没有客户到达变量 |
| `service_start_time` | 若 $j\in N^+$，计算 $t_{jm}+\varepsilon_{jm}^+$；若 $j=0$，置空或记为 `NA` | $t_{jm}+\varepsilon_{jm}^+$ | 实际开始服务时刻 |
| `service_end_time` | 若 $j\in N^+$，取 $D_{jm}=t_{jm}+\varepsilon_{jm}^+ +s_jv_{jm}$；若 $j=0$，置空或记为 `NA` | $D_{jm}$ | 客户服务完成时刻 |
| `load_weight` | 取弧段载荷 $q_{ijm}^w$ | $q_{ijm}^w$ | 弧上剩余重量 |
| `load_volume` | 取弧段载荷 $q_{ijm}^v$ | $q_{ijm}^v$ | 弧上剩余体积 |
| `load_ratio` | 计算 $\rho_{ijm}=q_{ijm}^w/Q_m^w$ | $\rho_{ijm}$ | 能耗修正输入 |
| `travel_time` | 计算 $\tau_{ij}(D_{im})$；也可由 `arrival_time - depart_time` 校验 | $\tau_{ij}(D_{im})$ | 时变旅行时间 |
| `energy_amount` | 计算 $E_{ijm}(D_{im},\rho_{ijm})x_{ijm}$ | $E_{ijm}(D_{im},\rho_{ijm})$ | 弧段能耗量 |
| `energy_cost` | 计算 $c_{ijm}^{energy}x_{ijm}=E_{ijm}(D_{im},\rho_{ijm})p_m^{energy}x_{ijm}$ | $c_{ijm}^{energy}x_{ijm}$ | 弧段能耗成本 |
| `co2_amount` | 计算 $Q_{ijm}^{CO_2}x_{ijm}=E_{ijm}(D_{im},\rho_{ijm})\eta_m^{CO_2}x_{ijm}$ | $Q_{ijm}^{CO_2}x_{ijm}$ | 弧段碳排放量 |
| `carbon_cost` | 计算 $c_{ijm}^{carbon}x_{ijm}=Q_{ijm}^{CO_2}\pi^{CO_2}x_{ijm}$ | $c_{ijm}^{carbon}x_{ijm}$ | 弧段碳成本 |
| `wait_time` | 若 $j\in N^+$，取 $\varepsilon_{jm}^+$；若 $j=0$，取 0 或 `NA` | $\varepsilon_{jm}^+$ | 客户等待量 |
| `late_time` | 若 $j\in N^+$，取 $\varepsilon_{jm}^-$；若 $j=0$，取 0 或 `NA` | $\varepsilon_{jm}^-$ | 客户迟到量 |

客户服务表至少包含：

| 输出字段 | 计算或生成方式 | 对应模型对象 | 备注 |
|---|---|---|---|
| `customer_id` | 对每个 $j\in N^+$ 输出客户编号 | $j$ | 索引字段 |
| `vehicle_id` | 对服务客户 $j$ 的车辆输出 $m$；通常保留 $v_{jm}=1$ 或 $\lambda_{jm}>0$ 的记录 | $m$ | 索引字段 |
| `visit_flag` | 计算 $v_{jm}=\sum_{i\in V,i\ne j}x_{ijm}$ | $v_{jm}$ | 派生访问变量 |
| `lambda` | 取 $\lambda_{jm}$ | $\lambda_{jm}$ | 服务比例 |
| `served_weight` | 计算 $\delta_{jm}^w=\lambda_{jm}W_j$ | $\delta_{jm}^w$ | 实际配送重量 |
| `served_volume` | 计算 $\delta_{jm}^v=\lambda_{jm}V_j$ | $\delta_{jm}^v$ | 实际配送体积 |
| `arrival_time` | 若 $v_{jm}=1$，取 $t_{jm}$；否则置空或记为 `NA` | $t_{jm}$ | 到达时刻 |
| `service_start_time` | 若 $v_{jm}=1$，计算 $t_{jm}+\varepsilon_{jm}^+$；否则置空或记为 `NA` | $t_{jm}+\varepsilon_{jm}^+$ | 实际开始服务时刻 |
| `service_end_time` | 若 $v_{jm}=1$，取 $D_{jm}$；否则置空或记为 `NA` | $D_{jm}$ | 实际完成服务时刻 |
| `wait_time` | 若 $v_{jm}=1$，取 $\varepsilon_{jm}^+$；否则取 0 或 `NA` | $\varepsilon_{jm}^+$ | 等待量 |
| `late_time` | 若 $v_{jm}=1$，取 $\varepsilon_{jm}^-$；否则取 0 或 `NA` | $\varepsilon_{jm}^-$ | 迟到量 |

车辆汇总表至少包含：

| 输出字段 | 计算或生成方式 | 对应模型对象 | 备注 |
|---|---|---|---|
| `vehicle_id` | 对每个 $m\in M$ 或每个 $y_m=1$ 的车辆输出编号 | $m$ | 索引字段 |
| `used` | 取 $y_m$ | $y_m$ | 车辆启用变量 |
| `return_time` | 若 $y_m=1$，取 $T_m^{ret}$；若 $y_m=0$，取 0 或 `NA` | $T_m^{ret}$ | 返仓时刻 |
| `route_distance` | 计算 $\sum_{(i,j)\in A}d_{ij}x_{ijm}$ | 派生量 | 车辆 $m$ 的总行驶距离 |
| `route_fixed_cost` | 计算 $f_my_m$ | 目标函数分项 | 车辆 $m$ 的固定成本 |
| `route_energy_cost` | 计算 $\sum_{(i,j)\in A}c_{ijm}^{energy}x_{ijm}$ | 目标函数分项 | 车辆 $m$ 的能耗成本 |
| `route_carbon_cost` | 计算 $\sum_{(i,j)\in A}c_{ijm}^{carbon}x_{ijm}$ | 目标函数分项 | 车辆 $m$ 的碳成本 |
| `route_wait_cost` | 计算 $p^{wait}\sum_{j\in N^+}\varepsilon_{jm}^+$ | 目标函数分项 | 车辆 $m$ 对应等待成本 |
| `route_late_cost` | 计算 $p^{late}\sum_{j\in N^+}\varepsilon_{jm}^-$ | 目标函数分项 | 车辆 $m$ 对应迟到成本 |
| `route_total_cost` | 计算 `route_fixed_cost + route_energy_cost + route_carbon_cost + route_wait_cost + route_late_cost` | 派生量 | 车辆 $m$ 的路线总成本 |

KPI 汇总表至少包含：

| 输出字段 | 计算或生成方式 | 对应模型对象 | 备注 |
|---|---|---|---|
| `total_cost` | 计算 $Z_1=C_{start}+C_{energy}+C_{carbon}+C_{wait}+C_{late}$ | $Z_1$ | Q1 总成本 |
| `fixed_cost` | 计算 $C_{start}=\sum_{m\in M}f_my_m$ | $C_{start}$ | 固定发车成本 |
| `energy_cost` | 计算 $C_{energy}=\sum_m\sum_{(i,j)\in A}c_{ijm}^{energy}x_{ijm}$ | $C_{energy}$ | 总能耗成本 |
| `carbon_cost` | 计算 $C_{carbon}=\sum_m\sum_{(i,j)\in A}c_{ijm}^{carbon}x_{ijm}$ | $C_{carbon}$ | 总碳成本 |
| `wait_cost` | 计算 $C_{wait}=p^{wait}\sum_j\sum_m\varepsilon_{jm}^+$ | $C_{wait}$ | 总等待成本 |
| `late_cost` | 计算 $C_{late}=p^{late}\sum_j\sum_m\varepsilon_{jm}^-$ | $C_{late}$ | 总迟到惩罚 |
| `total_distance` | 计算 $\sum_m\sum_{(i,j)\in A}d_{ij}x_{ijm}$ | 派生量 | 总行驶距离 |
| `used_vehicle_count` | 计算 $\sum_{m\in M}y_m$ | 派生量 | 启用车辆数 |
| `served_customer_count` | 统计满足 $\sum_{m\in M}\lambda_{jm}=1$ 的客户数 | 派生量 | 完成服务客户数 |
| `unassigned_task_count` | 理论模型中取 0；启发式中统计未被分配的服务单元或客户数 | 可行性检查 | 执行层检查项 |
| `total_co2` | 计算 $\sum_m\sum_{(i,j)\in A}Q_{ijm}^{CO_2}x_{ijm}$ | 派生量 | 总碳排放量 |

## 9. 一致性校验

本文件与源文件保持以下一致：
1. 只覆盖 Q1 静态配送基线模型。
2. 使用同一套 A1-A8 假设。
3. 使用同一套集合、参数、变量和派生量。
4. 使用同一目标函数。
5. 使用同一组需求、路径、载荷、容量、时间、时间窗和子回路约束。
6. 承认原始模型不是严格线性 MILP，实际求解需要离散化、查表或启发式近似。
