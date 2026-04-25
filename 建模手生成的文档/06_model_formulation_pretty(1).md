# Step 3 模型展开：TDSDHVRPTW 系列模型

## 当前阶段

- 当前阶段：`Step 3：confirmed 链的整题展开与代码补全`
- 本轮回溯边界：只展开已确认链条
  - `问题1`：baseline confirmed
  - `问题2`：candidate confirmed
  - `问题3`：给出动态重优化模型描述，但不把 candidate 写成 confirmed
- 本轮冻结对象：
  - `outputs/cleaned/` 标准化输入
  - `outputs/baseline/` 问题 1 与问题 3 baseline 结果
  - `outputs/candidate/` 问题 2 candidate 结果
  - `outputs/metrics/` 复判指标
- 本轮允许修改的文件范围：`analysis/`

## 1. 整题建模定位

本题不宜拆成三个互不相干的模型，而应按一条递进主链组织：

$$
\text{TDSDHVRPTW}
\;\longrightarrow\;
\text{TDSDHVRPTW-GAC}
\;\longrightarrow\;
\text{Dynamic TDSDHVRPTW}
$$

其中：

1. `问题1`：建立 `TDSDHVRPTW` 主模型，用于静态环境下的异构车队绿色配送调度。
2. `问题2`：在 `问题1` 基础上加入绿色配送区准入约束，形成 `TDSDHVRPTW-GAC`。
3. `问题3`：在 `问题2` 的路径状态基础上加入事件驱动的滚动重优化，形成 `Dynamic TDSDHVRPTW`。

这里的 `TDSDHVRPTW` 指：

- `TD`：Time-Dependent，时变旅行时间
- `SD`：Split Delivery，允许拆分配送
- `H`：Heterogeneous Fleet，异构车队
- `VRPTW`：Vehicle Routing Problem with Time Windows，带时间窗的车辆路径问题

本题还额外带有绿色成本，因此可理解为：

$$
\text{Green TDSDHVRPTW}
$$

即以 `TDSDHVRPTW` 为骨架、以绿色综合成本最小为目标的车辆路径模型。

## 2. 问题1模型假设

围绕当前客户节点层 `TDSDHVRPTW` 主模型，作如下建模假设：

| 编号 | 假设内容 | 说明 |
|---|---|---|
| A1 | 研究对象为单日静态配送，不考虑跨日排班 | 与题目场景一致，`Q1` 只求静态日计划 |
| A2 | 所有车辆均从唯一配送中心 `0` 出发，并在完成任务后返回配送中心 | 因而主模型采用单仓库闭合回路结构 |
| A3 | 仅正需求客户进入 `Q1` 主模型 | `cleaned_data` 中共有 `88` 个正需求客户；`1,14,15,17,18,20,21,22,23,96` 这 10 个零需求客户不参与 `Q1` 路径优化 |
| A4 | 同一客户的订单已在清洗阶段聚合为客户级需求，并共享同一客户级时间窗 | 主模型直接在客户层使用 $W_j,V_j,[e_j,l_j]$ |
| A5 | 所有时间变量统一采用“相对 8:00 的小时数”表示 | 例如 `8:00→0`，`9:00→1`，`11:30→3.5`，`13:00→5`，`15:00→7`，`16:00→8`，`17:00→9` |
| A6 | 各时段随机车速以题面给定正态分布的均值确定化 | 即用期望速度构造确定性 `TDVRP` 主模型 |
| A7 | 弧段旅行时间采用分段累计函数 $\tau_{ij}(t)$ 计算 | 即按出发时刻跨越的时段边界逐段积分，不采用“整段只看出发时段”的粗近似 |
| A8 | 允许拆分配送 | 同一客户可由多辆车分担，但各车辆承担的重量与体积保持客户总需求的同比例拆分 |
| A9 | 重量容量与体积容量独立施加 | 同时满足 $Q_m^w$ 与 $Q_m^v$ 两类约束 |
| A10 | 能耗修正由重量装载率驱动 | 以重量载重比而非体积载重比进入能耗修正项 |
| A11 | 不考虑途中加油、充电及补能设施选址 | 题目未给出补能网络信息，因此不在 `Q1` 主模型中显式建模 |
| A12 | 对超出题面显式给定时段范围的时刻，车速按中速区间均值外推 | 题面只给出 `8:00-17:00` 的分时段速度；为保证 $\tau_{ij}(t)$ 在规划域边界附近可计算，采用中速外推闭合时变旅行时间函数 |
| A13 | `Q1` 数学主模型按单趟单回路刻画 | 当前代码中同一车辆实例的多次复用属于启发式执行层，不作为本节严格数学主模型的核心设定 |
| A14 | 数学规划中的大常数统一记为 $\Omega$ | 避免与车辆实例集合 $M$ 混淆；$\Omega$ 只用于条件约束松弛 |

## 3. 符号系统

### 3.1 索引集合

| 符号 | 定义 | 说明 |
|---|---|---|
| $N=\{1,2,\dots,98\}$ | 全体客户集合 | 含零需求客户 |
| $N^+=\{j\in N\mid W_j>0\ \text{或}\ V_j>0\}$ | 正需求客户集合 | 基于 `cleaned_data`，当前 $n^+=88$，其中 $n^+=\lvert N^+\rvert$ |
| $V=\{0\}\cup N^+$ | 含配送中心的节点集合 | 节点 `0` 为配送中心 |
| $A=\{(i,j)\mid i,j\in V,\ i\neq j\}$ | 有向弧集 | 路径变量定义在该集合上 |
| $K=\{1,2,3,4,5\}$ | 车辆类型集合 | 对应 5 类车型 |
| $M$ | 车辆实例集合 | 每个实例 $m\in M$ 对应唯一车型 $\kappa(m)\in K$ |
| $N^{green}=\{j\in N^+\mid G_j=1\}$ | 正需求绿色区客户集合 | `Q2` 起进入主模型 |
| $M^{fuel}=\{m\in M\mid e(m)=\text{燃油}\}$ | 燃油车实例集合 | `Q2` 起进入主模型 |
| $M^{elec}=\{m\in M\mid e(m)=\text{新能源}\}$ | 新能源车实例集合 | 与 $M^{fuel}$ 一起构成车辆实例划分 |
| $\mathcal P=\{C,S,N\}$ | 路况时段集合 | 分别表示拥堵、顺畅、一般 |
| $\mathcal H=[0,T]$ | 规划时间域 | 以相对 `8:00` 的小时数表示，$T$ 取足够大以覆盖所有时间窗、等待、迟到和返仓时刻 |

并有：

$$
M=M^{fuel}\cup M^{elec},\qquad
M^{fuel}\cap M^{elec}=\varnothing
$$

### 3.2 参数

| 符号 | 单位 | 含义 | 备注 |
|---|---|---|---|
| $d_{ij}$ | km | 节点 $i$ 到节点 $j$ 的道路距离 | 来自距离矩阵 |
| $W_j,V_j$ | kg / m$^3$ | 客户 $j$ 的聚合重量 / 体积需求 | 来自清洗后客户表 |
| $e_j,l_j$ | h | 客户 $j$ 的最早 / 最晚到达时刻 | 相对 `8:00` 计时 |
| $s_j$ | h | 节点 $j$ 的服务时间 | 对 $j\in N^+$ 有 $s_j=1/3$，且 $s_0=0$ |
| $Q_m^w,Q_m^v$ | kg / m$^3$ | 车辆实例 $m$ 的重量 / 体积容量 | 由车型映射得到 |
| $f_m$ | 元 | 车辆实例 $m$ 的启动成本 | 本题取 $400$ |
| $e(m)$ | - | 车辆实例 $m$ 的能源类型 | 燃油或新能源 |
| $G_j$ | - | 客户 $j$ 的绿色区标记 | 按坐标规则计算 |
| $\bar v_p$ | km/h | 路况时段 $p$ 下的期望速度 | 对 $p\in\mathcal P$ 分别取 $9.8,55.3,35.4$ |
| $p_m^{\text{energy}}$ | 元/L 或 元/kWh | 车辆实例 $m$ 的单位能源价格 | 按能源类型取值 |
| $\eta_m^{CO_2}$ | kgCO$_2$/L 或 kgCO$_2$/kWh | 车辆实例 $m$ 的单位能源碳排放因子 | 按能源类型取值 |
| $\pi^{CO_2}$ | 元/kgCO$_2$ | 单位碳排放价格 | 用于将碳排放量转化为碳成本 |
| $p_m^{\text{carbon}}$ | 元/L 或 元/kWh | 与单位能源消耗对应的碳成本系数 | 等价于 $\eta_m^{CO_2}\pi^{CO_2}$ |
| $p^{wait},p^{late}$ | 元/h | 等待成本 / 迟到惩罚单价 | 本题取 $20,50$ |
| $T$ | h | 规划时间域上界 | 由数据最大时间窗和返仓裕度确定 |
| $\Omega$ | h 或无量纲 | 大常数 | 取不小于规划期内最大可能时刻差和最大可能路径序号差 |

单位能源价格按能源类型取值：

$$
p_m^{\text{energy}}=
\begin{cases}
p^{fuel}, & e(m)=\text{燃油} \\
p^{elec}, & e(m)=\text{新能源}
\end{cases}
$$

单位能源碳排放因子按能源类型取值：

$$
\eta_m^{CO_2}=
\begin{cases}
\eta_{fuel}^{CO_2}, & e(m)=\text{燃油} \\
\eta_{elec}^{CO_2}, & e(m)=\text{新能源}
\end{cases}
$$

碳成本系数为：

$$
p_m^{\text{carbon}}=\eta_m^{CO_2}\pi^{CO_2}
$$

### 3.3 决策变量

| 符号 | 类型 | 定义域 | 含义 |
|---|---|---|---|
| $x_{ijm}$ | 0-1变量 | $\{0,1\}$ | 车辆 $m$ 是否直接行驶弧 $(i,j)$ |
| $y_m$ | 0-1变量 | $\{0,1\}$ | 车辆 $m$ 是否被启用 |
| $\lambda_{jm}$ | 连续变量 | $[0,1]$ | 车辆 $m$ 承担客户 $j$ 需求的比例 |
| $q_{ijm}^w$ | 连续变量 | $[0,Q_m^w]$ | 车辆 $m$ 在弧 $(i,j)$ 上携带的剩余重量载荷 |
| $q_{ijm}^v$ | 连续变量 | $[0,Q_m^v]$ | 车辆 $m$ 在弧 $(i,j)$ 上携带的剩余体积载荷 |
| $t_{jm}$ | 连续变量 | $[0,+\infty)$ | 车辆 $m$ 到达客户 $j$ 的时刻 |
| $D_{im}$ | 连续变量 | $[0,+\infty)$ | 车辆 $m$ 离开节点 $i$ 的时刻 |
| $T_m^{ret}$ | 连续变量 | $[0,+\infty)$ | 车辆 $m$ 返回配送中心的时刻 |
| $\varepsilon_{jm}^+$ | 连续变量 | $[0,+\infty)$ | 车辆 $m$ 在客户 $j$ 处的提前到达量 |
| $\varepsilon_{jm}^-$ | 连续变量 | $[0,+\infty)$ | 车辆 $m$ 在客户 $j$ 处的迟到量 |
| $u_{jm}$ | 连续变量 | $[0,n^+]$ | 车辆 $m$ 访问客户 $j$ 时的路径序号，用于消除子回路 |

### 3.4 派生量与扩展符号

| 符号 | 类型 | 定义 | 角色 |
|---|---|---|---|
| $\delta_{jm}^w$ | 派生量 | $\delta_{jm}^w=\lambda_{jm}W_j$ | 车辆 $m$ 对客户 $j$ 实际承担的重量 |
| $\delta_{jm}^v$ | 派生量 | $\delta_{jm}^v=\lambda_{jm}V_j$ | 车辆 $m$ 对客户 $j$ 实际承担的体积 |
| $\rho_{ijm}$ | 派生量 | $\rho_{ijm}=q_{ijm}^w/Q_m^w$ | 能耗修正所用重量装载率 |
| $d_{ij}^{(p)}(t)$ | 派生量 | 车辆于时刻 $t$ 离开节点 $i$ 行驶弧 $(i,j)$ 时，在路况时段 $p$ 内完成的距离份额 | 满足 $\sum_{p\in\mathcal P}d_{ij}^{(p)}(t)=d_{ij}$ |
| $E_{ijm}(D_{im},\rho_{ijm})$ | 派生量 | 弧段 $(i,j)$ 上的实际能耗量 | 由分段速度与装载率共同决定 |
| $Q_{ijm}^{CO_2}$ | 派生量 | $Q_{ijm}^{CO_2}=E_{ijm}(D_{im},\rho_{ijm})\eta_m^{CO_2}$ | 弧段 $(i,j)$ 上的碳排放量 |
| $c_{ijm}^{\text{energy}}$ | 派生量 | 由弧段能耗量和能源价格共同决定 | 弧段能耗成本 |
| $c_{ijm}^{\text{carbon}}$ | 派生量 | $c_{ijm}^{\text{carbon}}=Q_{ijm}^{CO_2}\pi^{CO_2}$ | 弧段碳成本 |
| $v_{jm}$ | 派生量 | $v_{jm}=\sum_{i\in V,\ i\neq j}x_{ijm}$ | 客户 $j$ 是否被车辆 $m$ 访问 |
| $\mathcal S(t_r)$ | 状态对象 | 动态重优化时刻 $t_r$ 的系统状态 | `Q3` 主体对象 |
| $N^{done}(t_r),N^{part}(t_r)$ | 状态集合 | 已完成 / 部分完成客户集合 | `Q3` 状态分量 |
| $\bar W(t_r),\bar V(t_r)$ | 状态向量 | 时刻 $t_r$ 的剩余重量 / 体积需求 | `Q3` 状态分量 |
| $N^{new}(t_r),\Pi^{fix}(t_r)$ | 状态集合 | 新增需求集合 / 已冻结路径前缀 | `Q3` 状态分量 |

与先前 `service_unit` 离散化写法不同，Q1 主模型直接在客户节点层刻画拆分配送；代码中的 `service_units` 仅作为该主模型的启发式离散化求解对象。

### 3.5 标准化输入接口

Q1 主模型直接读取以下客户层 / 车辆层标准表：

- `outputs/cleaned/customer_demand.csv`
- `outputs/cleaned/customer_profile.csv`
- `outputs/cleaned/vehicles.csv`
- `outputs/cleaned/distance_long.csv`

其中：

- `customer_demand.csv` 提供 $W_j,V_j$
- `customer_profile.csv` 提供坐标、时间窗和绿色区标记
- `vehicles.csv` 提供车型和车辆实例参数
- `service_units.csv` 仅用于当前启发式求解器，不作为 Q1 主模型的基础对象

### 3.6 辅助函数定义

为使时变旅行时间与绿色成本计算闭合，进一步定义如下辅助函数。

#### 3.6.1 时段速度函数

题面给出的分时段速度均值，在当前模型中确定化为时段速度函数；其中对显式给定时段之外的部分，按假设 A12 做中速外推：

$$
v(t)=
\begin{cases}
9.8, & t\in[0,1)\cup[3.5,5) \\
55.3, & t\in[1,2)\cup[5,7) \\
35.4, & t\in[2,3.5)\cup[7,9) \\
35.4, & t\in[9,+\infty)
\end{cases}
$$

等价地，也可用时段判别函数 $P(t)$ 表示当前时刻所属路况区间，并写成 $v(t)=\bar v_{P(t)}$；正文为紧凑起见直接采用 $v(t)$。

#### 3.6.2 分段累计旅行时间函数

对任意弧 $(i,j)\in A$ 及离开时刻 $t\ge 0$，定义：

$$
\tau_{ij}(t)=\inf\left\{\Delta\ge 0:\int_t^{t+\Delta}v(u)\,\mathrm du\ge d_{ij}\right\}
$$

其含义是：车辆在时刻 $t$ 离开节点 $i$ 后，按时段速度函数 $v(\cdot)$ 在各时段边界上分段累计行驶，直到累计可行驶距离达到 $d_{ij}$ 时所需的最短时间。由于 $v(t)$ 为分段常值函数，上式与“按时段边界切割弧段并逐段累加”的实现完全一致。

#### 3.6.3 单位里程能耗率函数

燃油车与新能源车的基准单位里程能耗函数分别为：

$$
FPK(v)=0.0025v^2-0.2554v+31.75
$$

$$
EPK(v)=0.0014v^2-0.12v+36.19
$$

对应的满载修正因子为：

$$
\phi^{fuel}(\rho)=1+0.4\rho,\qquad
\phi^{new}(\rho)=1+0.35\rho
$$

于是车辆实例 $m$ 在速度 $v$、装载率 $\rho$ 下的单位里程能耗率函数定义为：

$$
\psi_m(v,\rho)=
\begin{cases}
FPK(v)\cdot \phi^{fuel}(\rho), & m\in M^{fuel} \\
EPK(v)\cdot \phi^{new}(\rho), & m\in M^{elec}
\end{cases}
$$

#### 3.6.4 弧段能耗量函数

由于弧段旅行时间 $\tau_{ij}(t)$ 已按时段边界分段累计，因此弧段 $(i,j)$ 的能耗也采用同一分段口径计算。记车辆在时刻 $t$ 离开节点 $i$ 行驶弧 $(i,j)$ 时，在各路况时段内完成的距离份额为 $d_{ij}^{(p)}(t)$，满足：

$$
\sum_{p\in\mathcal P} d_{ij}^{(p)}(t)=d_{ij}
$$

则车辆实例 $m$ 在弧段 $(i,j)$ 上的实际能耗量定义为：

$$
E_{ijm}(D_{im},\rho_{ijm})=
\begin{cases}
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}\,FPK(\bar v_p)\,\phi^{fuel}(\rho_{ijm}), & m\in M^{fuel} \\
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}\,EPK(\bar v_p)\,\phi^{new}(\rho_{ijm}), & m\in M^{elec}
\end{cases}
$$

该定义与分段累计旅行时间函数 $\tau_{ij}(t)$ 保持一致：若一条弧跨越多个速度时段，则能耗按各时段对应的速度均值分别计入，而不再用离开时刻的单一速度近似整条弧。

### 3.7 模型类型说明

需要注意，当前模型的原始数学形态不是严格线性 `MILP`。原因在于弧段旅行时间和弧段能耗均依赖决策变量：

$$
\tau_{ij}(D_{im})
$$

依赖车辆离开节点 $i$ 的时刻 $D_{im}$，而：

$$
E_{ijm}(D_{im},\rho_{ijm})
$$

同时依赖离开时刻 $D_{im}$ 与弧段装载率：

$$
\rho_{ijm}=\frac{q_{ijm}^w}{Q_m^w}
$$

其中 $D_{im}$ 和 $q_{ijm}^w$ 均为决策变量。因此，目标函数中的能耗成本与碳成本并不是固定弧成本系数，而是带有时间依赖和载荷依赖的变量函数。

所以，严格表述应为：

1. 原始模型是带时变旅行时间和载荷依赖能耗成本的混合整数非线性优化模型；
2. 若要转化为 `MILP`，需要对 $\tau_{ij}(\cdot)$、$E_{ijm}(\cdot,\cdot)$ 进行分段预计算、查表、分段线性化或离散化；
3. 当前代码求解层采用 `service_unit` 离散化与启发式近似求解，不宣称获得原始非线性模型的严格全局最优解。

## 4. 问题 1：TDSDHVRPTW 模型

### 4.1 模型目标

在无政策限制条件下，建立客户节点层的异构车队时变拆分配送模型，决定：

1. 哪些车辆被启用；
2. 每辆车访问哪些客户及访问顺序；
3. 各车辆分别承担每个客户多少比例的需求；
4. 各弧段上的载荷、到达时刻与时间窗惩罚；

使系统的综合运营成本最小。

### 4.2 核心定义式

客户 $j$ 的拆分配送比例定义为：

$$
\lambda_{jm}\in[0,1],\qquad \forall j\in N^+,\forall m\in M
$$

于是车辆 $m$ 对客户 $j$ 实际承担的重量与体积分别为：

$$
\delta_{jm}^w=\lambda_{jm}W_j,\qquad
\delta_{jm}^v=\lambda_{jm}V_j
$$

车辆离开客户 $j$ 的时刻写为：

$$
D_{jm}=t_{jm}+\varepsilon_{jm}^+ + s_jv_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

对配送中心约定：

$$
D_{0m}=0,\qquad \forall m\in M
$$

弧段 $(i,j)$ 上的能耗、碳排放量与碳成本分别写为：

$$
c_{ijm}^{\text{energy}}
=
E_{ijm}(D_{im},\rho_{ijm})\,p_m^{\text{energy}}
$$

$$
Q_{ijm}^{CO_2}
=
E_{ijm}(D_{im},\rho_{ijm})\,\eta_m^{CO_2}
$$

$$
c_{ijm}^{\text{carbon}}
=
Q_{ijm}^{CO_2}\,\pi^{CO_2}
=
E_{ijm}(D_{im},\rho_{ijm})\,p_m^{\text{carbon}}
$$

### 4.3 目标函数

以总成本最小化为目标：

$$
\min Z_1=C_{\text{start}}+C_{\text{energy}}+C_{\text{carbon}}+C_{\text{wait}}+C_{\text{late}}
$$

其中：

$$
C_{\text{start}}=\sum_{m\in M} f_m y_m
$$

$$
C_{\text{energy}}
=
\sum_{m\in M}\sum_{(i,j)\in A}
c_{ijm}^{\text{energy}}x_{ijm}
$$

$$
C_{\text{carbon}}
=
\sum_{m\in M}\sum_{(i,j)\in A}
c_{ijm}^{\text{carbon}}x_{ijm}
$$

$$
C_{\text{wait}}=p^{wait}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^+
$$

$$
C_{\text{late}}=p^{late}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^-
$$

### 4.4 紧致数学规划

将前述目标项与主约束收拢后，Q1 的 `TDSDHVRPTW` 主模型可写为：

$$
\begin{aligned}
\min Z_1
=\;&
\sum_{m\in M} f_m y_m
+\sum_{m\in M}\sum_{(i,j)\in A} c_{ijm}^{\text{energy}}x_{ijm} \\
&+\sum_{m\in M}\sum_{(i,j)\in A} c_{ijm}^{\text{carbon}}x_{ijm}
+p^{wait}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^+
+p^{late}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^-
\end{aligned}
$$

$$
\text{s.t.}
$$

$$
\sum_{m\in M}\lambda_{jm}=1,\qquad \forall j\in N^+
$$

$$
v_{jm}=\sum_{i\in V,\ i\neq j}x_{ijm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
0\le \lambda_{jm}\le v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{i\in V,\ i\neq j}x_{ijm}
=
\sum_{l\in V,\ l\neq j}x_{jlm}
\le 1,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{j\in N^+}x_{0jm}=y_m,\qquad
\sum_{i\in N^+}x_{i0m}=y_m,\qquad \forall m\in M
$$

$$
\sum_{i\in V,\ i\neq j}q_{ijm}^w
-\sum_{l\in V,\ l\neq j}q_{jlm}^w
=\lambda_{jm}W_j,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{i\in V,\ i\neq j}q_{ijm}^v
-\sum_{l\in V,\ l\neq j}q_{jlm}^v
=\lambda_{jm}V_j,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{j\in N^+}q_{0jm}^w
=
\sum_{j\in N^+}\lambda_{jm}W_j,\qquad \forall m\in M
$$

$$
\sum_{j\in N^+}q_{0jm}^v
=
\sum_{j\in N^+}\lambda_{jm}V_j,\qquad \forall m\in M
$$

$$
0\le q_{ijm}^w \le Q_m^w x_{ijm},\qquad \forall (i,j)\in A,\forall m\in M
$$

$$
0\le q_{ijm}^v \le Q_m^v x_{ijm},\qquad \forall (i,j)\in A,\forall m\in M
$$

$$
D_{jm}=t_{jm}+\varepsilon_{jm}^+ + s_jv_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
D_{0m}=0,\qquad \forall m\in M
$$

$$
t_{jm}\ge \tau_{0j}(0)-\Omega(1-x_{0jm}),\qquad \forall j\in N^+,\forall m\in M
$$

$$
t_{jm}\ge D_{im}+\tau_{ij}(D_{im})-\Omega(1-x_{ijm}),
\quad \forall i\in N^+,\forall j\in N^+,\ i\neq j,\forall m\in M
$$

$$
T_m^{ret}\ge D_{im}+\tau_{i0}(D_{im})-\Omega(1-x_{i0m}),\qquad \forall i\in N^+,\forall m\in M
$$

$$
\varepsilon_{jm}^+ \ge e_j-t_{jm}-\Omega(1-v_{jm}),\qquad
\varepsilon_{jm}^- \ge t_{jm}-l_j-\Omega(1-v_{jm}),\qquad
\forall j\in N^+,\forall m\in M
$$

$$
t_{jm}\le \Omega v_{jm},\qquad
D_{jm}\le \Omega v_{jm},\qquad
\varepsilon_{jm}^+\le \Omega v_{jm},\qquad
\varepsilon_{jm}^-\le \Omega v_{jm}
$$

$$
v_{jm}\le y_m,\qquad \forall j\in N^+,\forall m\in M
$$

$$
0\le u_{jm}\le n^+v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
u_{im}-u_{jm}+n^+x_{ijm}\le n^+-1,
\qquad \forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

$$
x_{ijm}\in\{0,1\},\qquad y_m\in\{0,1\},\qquad 0\le \lambda_{jm}\le 1
$$

$$
q_{ijm}^w,q_{ijm}^v,t_{jm},D_{jm},T_m^{ret},\varepsilon_{jm}^+,\varepsilon_{jm}^-,u_{jm} \ge 0
$$

上述主模型站在客户节点层直接刻画 split-delivery；后续代码中构造的 `service_unit` 只是将 $\lambda_{jm}$ 的连续拆分结果离散化为可执行任务，以便用启发式算法求近似解。

其中 $v_{jm}$ 将“车辆 $m$ 是否访问客户 $j$”显式化，便于后续绿色准入约束、时间变量关闭约束和输出统计共用；$u_{jm}$ 只承担子回路消除作用，不进入目标函数。若某车辆未访问客户 $j$，则 $v_{jm}=0$ 会同时强制 $\lambda_{jm},t_{jm},D_{jm},\varepsilon_{jm}^+,\varepsilon_{jm}^-$ 关闭，避免未访问节点产生虚假的等待或迟到成本。

### 4.5 约束体系

#### 1. 需求满足与拆分约束

$$
\sum_{m\in M}\lambda_{jm}=1,\qquad \forall j\in N^+
$$

$$
v_{jm}=\sum_{i\in V,\ i\neq j}x_{ijm},\qquad
0\le \lambda_{jm}\le v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

来源：客户 $j$ 的需求允许由多辆车分担，但每一份拆分都必须对应一次真实访问。

#### 2. 路径连续性与车辆启用约束

$$
\sum_{i\in V,\ i\neq j}x_{ijm}
=
\sum_{l\in V,\ l\neq j}x_{jlm}
\le 1,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{j\in N^+}x_{0jm}=y_m,\qquad
\sum_{i\in N^+}x_{i0m}=y_m,\qquad \forall m\in M
$$

来源：每辆启用车辆恰好从配送中心出发一次并返回一次；同一车辆对同一客户至多访问一次。

#### 3. 重量与体积载荷流守恒约束

$$
\sum_{i\in V,\ i\neq j}q_{ijm}^w
-\sum_{l\in V,\ l\neq j}q_{jlm}^w
=\lambda_{jm}W_j,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{i\in V,\ i\neq j}q_{ijm}^v
-\sum_{l\in V,\ l\neq j}q_{jlm}^v
=\lambda_{jm}V_j,\qquad \forall j\in N^+,\forall m\in M
$$

$$
\sum_{j\in N^+}q_{0jm}^w
=
\sum_{j\in N^+}\lambda_{jm}W_j,\qquad
\sum_{j\in N^+}q_{0jm}^v
=
\sum_{j\in N^+}\lambda_{jm}V_j
$$

来源：车辆从配送中心出发时装载本车承担的全部需求，并在访问客户后按实际配送量逐步卸货。

#### 4. 容量约束

$$
0\le q_{ijm}^w \le Q_m^w x_{ijm},\qquad
0\le q_{ijm}^v \le Q_m^v x_{ijm}
$$

来源：每条已使用弧上的重量和体积载荷都不能超过对应车辆容量。

#### 5. 时变时间传播约束

$$
D_{jm}=t_{jm}+\varepsilon_{jm}^+ + s_jv_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
t_{jm}\ge \tau_{0j}(0)-\Omega(1-x_{0jm}),\qquad
t_{jm}\ge D_{im}+\tau_{ij}(D_{im})-\Omega(1-x_{ijm})
$$

$$
T_m^{ret}\ge D_{im}+\tau_{i0}(D_{im})-\Omega(1-x_{i0m})
$$

来源：题面明确给出分时段车速，因此每一弧段的行驶时间由离开前一节点的时刻决定；这里采用分段累计旅行时间函数 $\tau_{ij}(\cdot)$。

#### 6. 软时间窗约束

$$
\varepsilon_{jm}^+ \ge e_j-t_{jm}-\Omega(1-v_{jm}),\qquad
\varepsilon_{jm}^- \ge t_{jm}-l_j-\Omega(1-v_{jm}),\qquad
\forall j\in N^+,\forall m\in M
$$

来源：提前到达只产生等待成本，延迟到达产生罚金，时间窗以软约束形式进入目标函数。

#### 7. 子回路消除约束

$$
0\le u_{jm}\le n^+v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
u_{im}-u_{jm}+n^+x_{ijm}\le n^+-1,
\qquad \forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

来源：仅有流平衡时可能出现与配送中心脱离的客户子回路；引入 $u_{jm}$ 后，每辆车的已访问客户必须形成从配送中心出发并最终回到配送中心的单一闭合路径。

### 4.6 结果解释

`问题1` 的数学主模型现已统一为客户节点层的 split-delivery 形式；当前 confirmed baseline 代码则使用 `service_unit` 离散化启发式对该主模型求近似解。真实运行结果见：

- `outputs/metrics/question1_baseline_metrics.json`

当前最优保留链的主要特征为：

- 综合总成本最低
- 迟到单元数 `22`
- 混合使用燃油与新能源大车

## 5. 问题 2：TDSDHVRPTW-GAC 模型

### 5.1 模型目标

在 `问题1` 的 `TDSDHVRPTW` 骨架上，加入绿色配送区准入约束，分析政策对总成本、车辆结构与排放的影响。

### 5.1.1 问题2补充假设

在继承 `Q1` 假设的基础上，`Q2` 增加如下政策假设：

1. 绿色区客户集合按清洗后坐标口径确定，且只把正需求绿色区客户纳入 $N^{green}$；
2. 绿色准入政策只限制燃油车，新能源车辆不受该禁入规则限制；
3. 准入判断以车辆到达绿色区客户的时刻 $t_{jm}$ 为准，不再额外区分进入绿色区边界的路段时刻；
4. 政策实施不改变客户需求、车辆容量、服务时间和单位能源价格，只改变可行路径集合；
5. 若燃油车服务绿色区客户，则必须在 `16:00` 之后到达；否则该车辆-客户服务关系不可行。

### 5.2 新增参数

绿色区标记：

$$
G_j=
\begin{cases}
1, & j\in N^{green} \\
0, & \text{otherwise}
\end{cases}
$$

其中当前按坐标规则识别出的绿色区客户总数为 `15`；但 `Q1/Q2` 主模型只对正需求客户建模，因此进入 $N^{green}$ 的是其中有实际配送需求的绿色区客户，当前为 `12` 个。该口径与 `cleaned_data` 一致，不再混用题面文字中的 `30` 个绿色区客户表述。

燃油车标记：

$$
F_m=
\begin{cases}
1, & e(m)=\text{燃油} \\
0, & e(m)=\text{新能源}
\end{cases}
$$

进一步记：

$$
N^{green}=\{j\in N^+\mid G_j=1\},\qquad
M^{fuel}=\{m\in M\mid F_m=1\}
$$

### 5.3 新增准入约束（GAC）

由于本模型按假设 A5 将时间变量设为相对 `8:00` 的小时数，因此 `16:00` 对应 $t=8$。同时本题配送计划从 `8:00` 开始，规划域内不存在“`8:00` 之前服务绿色区客户”的可执行分支，所以题面“燃油车 `8:00-16:00` 禁入绿色区”在当前时间口径下等价收缩为：燃油车若服务绿色区客户，则到达时刻不得早于 `16:00`，即不得早于 $t=8$。

记访问指示量为：

$$
v_{jm}=\sum_{i\in V,\ i\neq j}x_{ijm},\qquad \forall j\in N^+,\forall m\in M
$$

则绿色准入约束可写为：

$$
t_{jm}\ge 8 - \Omega(1-v_{jm}),
\qquad \forall j\in N^{green},\forall m\in M^{fuel}
$$

当 $v_{jm}=1$ 时，上式强制燃油车访问绿色区客户的到达时刻满足 $t_{jm}\ge 8$，即只能在 `16:00` 之后进入；当 $v_{jm}=0$ 时，约束自动松弛。这样便把“`8:00-16:00` 禁入”的政策规则转化为与当前时间单位完全一致的线性准入约束。

### 5.4 问题 2 目标函数

目标函数仍保持：

$$
\min Z_2=C_{\text{start}}+C_{\text{energy}}+C_{\text{carbon}}+C_{\text{wait}}+C_{\text{late}}
$$

但由于准入约束改变了可行域，最优路径结构与车型分配会发生变化。

更紧凑地，`问题2` 可写为：

$$
\begin{aligned}
\min\quad & Z_2\\
\text{s.t.}\quad
& \text{Q1 中 TDSDHVRPTW 的全部约束},\\
& t_{jm}\ge 8-\Omega(1-v_{jm}),\qquad
  \forall j\in N^{green},\forall m\in M^{fuel}.
\end{aligned}
$$

因此 `Q2` 不是重建一套新的目标函数，而是在 `Q1` 目标结构不变的情况下加入绿色准入约束，收紧可行域。该约束会通过可行路径集合变化进一步影响车型分配、访问顺序、等待时间、迟到结构、能耗成本和碳成本。

### 5.5 问题 2 输出定义

`问题2` 的结果输出应至少包含以下对象：

1. 政策约束后的车辆路径方案，即每辆被启用车辆的访问序列与到达时刻；
2. 客户服务分配表，即每个客户由哪些车辆承担、承担比例 $\lambda_{jm}$ 及对应配送量；
3. 绿色区客户服务结构，即绿色区客户由燃油车与新能源车服务的比例、数量和需求量；
4. 政策增量成本，即 $Z_2-Z_1$ 及启动、能耗、碳排、等待、迟到各分项变化；
5. 时间窗变化结果，即总等待时长、总迟到时长、迟到客户数或迟到任务数变化；
6. 环境影响变化，即能源消耗量、碳成本和碳排代理指标的变化。

### 5.6 结果解释

已确认链条采用的是 `q2_policy_candidate`，对应指标见：

- `outputs/metrics/candidate_question2_compare.json`

需要注意，该文件中的政策增量采用的是 `q1_static_candidate -> q2_policy_candidate` 的同一候选链对比口径，而不是 `question1_baseline_metrics.json` 中的 baseline 口径。按该候选链口径，政策影响为：

- 绿色区服务车型结构是否由燃油车转向新能源车；
- 政策成本增量约 `2110.16`；
- 迟到单元数从 `13` 增至 `22`；
- 总能耗成本、碳成本和等待成本是否发生替代变化。

若改用正文 `Q1 baseline` 结果作为比较基准，则应重新计算：

$$
\Delta Z_{21}=Z_2-Z_1
$$

不能把 baseline 结果与 candidate 增量混用。

因此 `问题2` 的 confirmed 主链是：

$$
\text{TDSDHVRPTW-GAC}
$$

并由 candidate 求解链支撑。

## 6. 问题 3：Dynamic TDSDHVRPTW

### 6.1 模型目标

在配送执行过程中，遇到新增订单、取消订单、地址变更或时间窗变化时，不重启整日静态计划，而是在当前状态上做事件驱动的滚动重优化。

### 6.1.1 问题3补充假设

在继承 `Q1/Q2` 约束体系的基础上，`Q3` 增加如下动态假设：

1. 动态事件只影响当前时刻之后尚未执行的计划，已服务客户和已完成弧段不回滚；
2. 正在行驶的车辆不可中途掉头或中断当前弧段，只能在完成当前弧段后进入重优化；
3. 新增订单、取消订单、地址变化和时间窗变化均在事件时刻 $t_r$ 被即时观测；
4. 地址变化会同步更新距离矩阵、旅行时间函数和弧段能耗函数中相关行列；
5. 动态重优化仍采用同一套容量、时间窗、能耗、碳成本和绿色准入规则；
6. 若实时计算时间相对配送执行时间很短，则忽略求解耗时对车辆状态的影响；否则应把求解耗时并入 $t_r$ 后的车辆可用时刻。

### 6.2 状态定义

在重优化时刻 $t_r$，系统状态写为：

$$
\mathcal{S}(t_r)=
\Big(
M^{act}(t_r),
N^{done}(t_r),
N^{part}(t_r),
N^{todo}(t_r),
\bar{W}(t_r),
\bar{V}(t_r),
N^{new}(t_r),
\Pi^{fix}(t_r),
\Pi^{old,rem}(t_r)
\Big)
$$

其中：

- $M^{act}(t_r)$：当前仍可继续调度的车辆集合及其当前位置、剩余容量、当前时刻和可用状态
- $N^{done}(t_r)$：需求已全部完成的客户集合
- $N^{part}(t_r)$：已部分服务但仍有剩余需求的客户集合
- $N^{todo}(t_r)$：尚未服务且仍有需求的原计划客户集合
- $\bar{W}(t_r),\bar{V}(t_r)$：各客户在时刻 $t_r$ 的剩余重量 / 体积需求向量
- $N^{new}(t_r)$：事件触发后新增的客户或新增需求集合
- $\Pi^{fix}(t_r)$：已执行路径前缀，视为冻结
- $\Pi^{old,rem}(t_r)$：事件发生前尚未执行的原计划后缀，用于计算方案扰动幅度

据此定义剩余待服务集合：

$$
N^{rem}(t_r)=
\left\{j\in N^+\cup N^{new}(t_r)\mid
\bar W_j(t_r)>0\ \text{或}\ \bar V_j(t_r)>0
\right\}
$$

其中 $N^{done}(t_r)$ 不再进入重优化的需求满足约束；$N^{part}(t_r)$ 只以剩余需求 $\bar W_j(t_r),\bar V_j(t_r)$ 进入模型。

残余节点集和残余弧集按车辆分别定义。对每辆仍可调度车辆 $m\in M^{act}(t_r)$，记：

$$
V_m^{(r)}=\{o_m(t_r)\}\cup N^{rem}(t_r)\cup\{0\}
$$

$$
A_m^{(r)}=\{(i,j)\mid i,j\in V_m^{(r)},\ i\neq j\}
$$

其中 $o_m(t_r)$ 为车辆 $m$ 在重优化时刻的当前位置；若车辆正在弧上行驶，则按冻结前缀规则将其位置更新为在途弧完成后的节点。采用每车残余弧集 $A_m^{(r)}$ 的目的是防止车辆 $m$ 从其他车辆的位置出发。

### 6.2.1 Q3 新增参数与状态符号

动态重优化中新增使用以下符号：

| 符号 | 类型 | 含义 |
|---|---|---|
| $o_m(t_r)$ | 状态量 | 车辆 $m$ 在重优化时刻的有效起点；若正在行驶，则取当前弧完成后的节点 |
| $t_m^{avail}(t_r)$ | 状态量 | 车辆 $m$ 可重新参与调度的最早时刻 |
| $\bar Q_m^w(t_r),\bar Q_m^v(t_r)$ | 状态量 | 车辆 $m$ 在时刻 $t_r$ 后可用的剩余重量 / 体积容量 |
| $f_m^{(r)}$ | 参数 | 残余优化中的车辆启动成本；已启动车辆取 `0`，新启动车辆取 $f_m$ |
| $p_j^{delay}$ | 参数 | 新增订单 $j$ 的响应延迟惩罚系数 |
| $p^{chg}$ | 参数 | 路径扰动惩罚系数 |
| $\hat x_{ijm}^{rem}(t_r)$ | 状态量 | 事件发生前原计划后缀中车辆 $m$ 是否使用弧 $(i,j)$ |
| $\tau_{ab}^{rem}(t_r)$ | 状态量 | 车辆在时刻 $t_r$ 位于弧 $(a,b)$ 上时的剩余行驶时间 |

### 6.3 动态决策变量

在事件时刻 $t_r$ 后的剩余规划域内，重新定义残余问题变量：

| 符号 | 类型 | 含义 |
|---|---|---|
| $x_{ijm}^{(r)}$ | 0-1变量 | 重优化后车辆 $m$ 是否在剩余计划中直接行驶弧 $(i,j)\in A_m^{(r)}$ |
| $y_m^{(r)}$ | 0-1变量 | 车辆 $m$ 在重优化后是否继续被使用 |
| $\lambda_{jm}^{(r)}$ | 连续变量 | 车辆 $m$ 承担客户 $j$ 剩余需求的比例 |
| $q_{ijm}^{w,(r)},q_{ijm}^{v,(r)}$ | 连续变量 | 重优化后弧段上的剩余重量 / 体积载荷 |
| $t_{jm}^{(r)}$ | 连续变量 | 重优化后车辆 $m$ 到达客户 $j$ 的时刻 |
| $D_{im}^{(r)}$ | 连续变量 | 重优化后车辆 $m$ 离开节点 $i$ 的时刻 |
| $\varepsilon_{jm}^{+,(r)},\varepsilon_{jm}^{-,(r)}$ | 连续变量 | 重优化后的等待量 / 迟到量 |
| $R_j^{(r)}$ | 连续变量 | 新增订单 $j$ 的响应延迟量 |
| $v_{jm}^{(r)}$ | 派生量 | $v_{jm}^{(r)}=\sum_{i\in V_m^{(r)},i\neq j}x_{ijm}^{(r)}$ |

这些变量与 `Q1/Q2` 中的变量含义一致，但作用对象从“全天全部正需求客户”变为“时刻 $t_r$ 之后仍需处理的剩余任务”。

### 6.4 动态目标函数

在每个事件时刻求解：

$$
\min Z_3(\mathcal{S}(t_r))
=
C_{\text{rem}}^{(r)}
+C_{\text{delay}}^{(r)}
+C_{\text{wait}}^{(r)}
+C_{\text{late}}^{(r)}
+C_{\text{disrupt}}^{(r)}
$$

其中：

$$
C_{\text{rem}}^{(r)}
=
\sum_{m\in M^{act}(t_r)} f_m^{(r)} y_m^{(r)}
+\sum_{m\in M^{act}(t_r)}\sum_{(i,j)\in A_m^{(r)}}
\left(c_{ijm}^{\text{energy},(r)}+c_{ijm}^{\text{carbon},(r)}\right)x_{ijm}^{(r)}
$$

表示剩余任务的车辆启动、能耗与碳成本。其中 $f_m^{(r)}$ 是残余启动成本：若车辆在 $t_r$ 前已经启动，则 $f_m^{(r)}=0$；若车辆在重优化后才被启用，则 $f_m^{(r)}=f_m$，从而避免重复计入固定发车成本。

$$
C_{\text{delay}}^{(r)}
=
\sum_{j\in N^{new}(t_r)} p_j^{delay}R_j^{(r)}
$$

表示新增订单的响应延迟惩罚，其中 $R_j^{(r)}$ 可由以下约束给出：

$$
R_j^{(r)}\ge t_{jm}^{(r)}-e_j-\Omega(1-v_{jm}^{(r)}),
\qquad \forall j\in N^{new}(t_r),\forall m\in M^{act}(t_r)
$$

$$
R_j^{(r)}\ge 0,\qquad \forall j\in N^{new}(t_r)
$$

若新增订单只要求必须完成、不强调响应速度，则可令 $p_j^{delay}=0$，此时新增订单只通过路径、容量和时间窗成本体现。

$$
C_{\text{wait}}^{(r)}
=p^{wait}\sum_{j\in N^{rem}(t_r)}\sum_{m\in M^{act}(t_r)}
\varepsilon_{jm}^{+,(r)}
$$

$$
C_{\text{late}}^{(r)}
=p^{late}\sum_{j\in N^{rem}(t_r)}\sum_{m\in M^{act}(t_r)}
\varepsilon_{jm}^{-,(r)}
$$

方案扰动成本用于抑制重优化对尚未执行计划的过度改动，可定义为：

$$
C_{\text{disrupt}}^{(r)}
=
p^{chg}
\sum_{m\in M^{act}(t_r)}
\sum_{(i,j)\in A_m^{(r)}}
\left|x_{ijm}^{(r)}-\hat x_{ijm}^{rem}(t_r)\right|
$$

其中 $\hat x_{ijm}^{rem}(t_r)$ 为事件发生前原计划后缀中的弧选择。若采用线性规划求解，可引入辅助变量将绝对值线性化；若采用启发式求解，则可直接按弧差异数或客户访问顺序差异计算扰动分。

### 6.5 约束继承关系

`Q3` 的残余重优化模型不是另起炉灶，而是在当前状态上继承 `Q1/Q2` 的约束结构：

1. 对 $N^{rem}(t_r)$ 继承 `Q1` 的需求满足、拆分配送、路径流平衡、容量、载荷传播、时间传播、软时间窗和子回路消除约束；
2. 若处于绿色区政策场景，则继续继承 `Q2` 的 GAC 约束；
3. 已完成客户 $j\in N^{done}(t_r)$ 不再参与需求满足约束，且不得被重新分配；
4. 部分完成客户 $j\in N^{part}(t_r)$ 只按剩余需求 $\bar W_j(t_r),\bar V_j(t_r)$ 建模；
5. 车辆起点不再统一为配送中心，而是各车辆在 $t_r$ 的实际位置。

残余需求满足约束写为：

$$
\sum_{m\in M^{act}(t_r)}\lambda_{jm}^{(r)}=1,
\qquad \forall j\in N^{rem}(t_r)
$$

实际承担量改为：

$$
\delta_{jm}^{w,(r)}=\lambda_{jm}^{(r)}\bar W_j(t_r),\qquad
\delta_{jm}^{v,(r)}=\lambda_{jm}^{(r)}\bar V_j(t_r)
$$

容量约束按车辆在 $t_r$ 后的可用容量重写。若车辆不允许中途回仓补装，则：

$$
0\le q_{ijm}^{w,(r)}\le \bar Q_m^w(t_r)x_{ijm}^{(r)},\qquad
0\le q_{ijm}^{v,(r)}\le \bar Q_m^v(t_r)x_{ijm}^{(r)},
\qquad \forall (i,j)\in A_m^{(r)},\forall m\in M^{act}(t_r)
$$

若允许车辆先回仓再补装，则回仓后的后续弧段容量上界恢复为 $Q_m^w,Q_m^v$；本文动态模型默认采用“不回滚已装载状态、只优化剩余后缀”的口径。

绿色准入约束在动态阶段保持为：

$$
t_{jm}^{(r)}\ge 8-\Omega(1-v_{jm}^{(r)}),
\qquad \forall j\in N^{green}\cap N^{rem}(t_r),\forall m\in M^{fuel}
$$

车辆残余路径必须从各自的有效起点 $o_m(t_r)$ 出发，并最终返回配送中心：

$$
\sum_{j\in V_m^{(r)},\ j\neq o_m(t_r)}
x_{o_m(t_r),jm}^{(r)}
=y_m^{(r)},\qquad \forall m\in M^{act}(t_r)
$$

$$
\sum_{i\in V_m^{(r)},\ i\neq 0}
x_{i0m}^{(r)}
=y_m^{(r)},\qquad \forall m\in M^{act}(t_r)
$$

因此车辆 $m$ 不能从其他车辆的当前位置出发；其残余路径起点由当前状态 $\mathcal S(t_r)$ 唯一确定。

### 6.6 冻结前缀与残余优化边界

冻结前缀 $\Pi^{fix}(t_r)$ 用来保证已经执行或正在执行的路径不被重优化回滚。更严格地说，已完成前缀不应继续作为残余模型的决策弧，而应从残余优化中剔除，并只作为系统状态更新的输入。

若弧 $(i,j,m)$ 已经在 $t_r$ 前完成，则对应的历史决策不再进入车辆 $m$ 的残余决策变量：

$$
x_{ijm}^{(r)}\ \text{不再定义},\qquad (i,j,m)\in \Pi^{fix}(t_r)\ \text{且该弧已完成}
$$

该弧的作用只体现在状态更新中：更新车辆 $m$ 的当前位置、当前时刻、剩余重量容量、剩余体积容量以及已完成客户集合 $N^{done}(t_r)$。因此，残余优化只决定 $t_r$ 之后尚未执行的路径后缀。

若车辆 $m$ 在时刻 $t_r$ 正在弧 $(a,b)$ 上行驶，则该在途弧不可中断，车辆的重优化起点更新为该弧完成后的节点 $b$，最早可用时刻为：

$$
t_m^{avail}(t_r)=t_r+\tau_{ab}^{rem}(t_r)
$$

其中 $\tau_{ab}^{rem}(t_r)$ 表示弧 $(a,b)$ 的剩余行驶时间。随后该车辆只能从位置 $b$ 开始进入剩余路径优化：

$$
D_{b m}^{(r)}\ge t_m^{avail}(t_r)
$$

对已完成客户：

$$
\lambda_{jm}^{(r)}=0,\qquad v_{jm}^{(r)}=0,
\qquad \forall j\in N^{done}(t_r),\forall m\in M
$$

上述处理保证动态重优化只作用于“当前时刻之后尚未执行的部分”。已完成路径前缀不再进入残余决策变量，在途弧只通过车辆可用位置和可用时刻进入后续优化，从而避免在残余模型中固定已经不存在的历史弧。

### 6.7 事件类型的数学更新

事件驱动规则写成：

$$
\mathcal{S}(t_r^+) = \Phi\big(\mathcal{S}(t_r^-), \mathcal{E}(t_r)\big)
$$

其中 $\mathcal{E}(t_r)$ 为时刻 $t_r$ 发生的事件集合。四类典型事件分别更新如下。

**新增订单。** 若新增客户或新增需求为 $j^*$，则：

$$
N^{new}(t_r^+)=N^{new}(t_r^-)\cup\{j^*\}
$$

$$
\bar W_{j^*}(t_r^+)=W_{j^*}^{new},\qquad
\bar V_{j^*}(t_r^+)=V_{j^*}^{new}
$$

并补充其坐标、时间窗和绿色区标记后进入 $N^{rem}(t_r^+)$。

**取消订单。** 若客户 $j^*$ 的未执行需求取消，则：

$$
\bar W_{j^*}(t_r^+)=0,\qquad
\bar V_{j^*}(t_r^+)=0
$$

若 $j^*$ 尚未被服务，则从 $N^{rem}(t_r^+)$ 中移除；若已部分服务，则保留已完成事实，不回滚已发生配送。

**地址变化。** 若客户 $j^*$ 的地址变化，则更新其坐标：

$$
(x_{j^*},y_{j^*})^{+}=(x_{j^*},y_{j^*})^{new}
$$

并重新计算距离矩阵中与 $j^*$ 相关的行列：

$$
d_{ij^*}^{+},d_{j^*i}^{+},\qquad \forall i\in V\cup N^{new}(t_r)
$$

进而更新对应的 $\tau_{ij^*}(\cdot)$、$\tau_{j^*i}(\cdot)$ 和能耗成本函数。

**时间窗变化。** 若客户 $j^*$ 的服务时间窗变化，则：

$$
[e_{j^*}^{+},l_{j^*}^{+}]
=
[e_{j^*}^{new},l_{j^*}^{new}]
$$

其余路径、容量和绿色准入约束保持不变，但等待变量和迟到变量按新时间窗重新计算。

### 6.8 当前保留链

`问题3` 当前保留 baseline 动态链，数学模型定位为 `Dynamic TDSDHVRPTW`，即在 `Q1/Q2` 的剩余可行域上做事件驱动滚动重优化。当前已跑的事件样例为：

- 在执行过程中新增客户 `25` 的紧急剩余需求

对应结果见：

- `outputs/metrics/question3_dynamic_cases.json`

## 7. 结果输出层定义

模型章节不仅要说明“怎么建模”，还要明确每一问最终输出什么对象，便于结果分析章节直接承接。

### 7.1 问题 1 输出

`Q1` 作为无政策基线，应输出：

1. 车辆路径表：每辆启用车辆的客户访问序列、到达时刻、离开时刻和返仓时刻；
2. 客户服务分配表：每个客户由哪些车辆服务、服务比例 $\lambda_{jm}$、对应重量和体积；
3. 成本分解表：$C_{\text{start}},C_{\text{energy}},C_{\text{carbon}},C_{\text{wait}},C_{\text{late}}$ 及总成本 $Z_1$；
4. 时间窗满足情况：每个客户的等待量、迟到量、是否发生迟到；
5. 车辆使用结构：燃油车 / 新能源车启用数量、车型结构和容量利用率。

### 7.2 问题 2 输出

`Q2` 作为绿色区政策场景，应输出：

1. 加入 GAC 后的车辆路径表；
2. 绿色区客户服务结构，即 $N^{green}$ 内客户由燃油车和新能源车承担的比例；
3. 政策增量成本 $\Delta Z_{21}=Z_2-Z_1$；
4. 分项成本变化 $\Delta C_{\text{start}},\Delta C_{\text{energy}},\Delta C_{\text{carbon}},\Delta C_{\text{wait}},\Delta C_{\text{late}}$；
5. 迟到变化、等待变化和绿色区服务可行性；
6. 燃油车进入绿色区的违约次数。若模型严格施加 GAC，该指标应为 `0`。

### 7.3 问题 3 输出

`Q3` 作为动态场景，应输出：

1. 事件前后路径调整表，即每个事件触发前后的车辆路径差异；
2. 新增、取消、地址变化和时间窗变化事件的处理结果；
3. 动态重优化后的服务完成率、未完成客户数和未完成需求量；
4. 动态增量成本 $\Delta Z_3=Z_3-Z_{\text{static-rem}}$；
5. 方案扰动幅度，即重优化后与原计划后缀相比改变的弧数、客户顺序差异或车辆重分配次数；
6. 动态响应成功率，即事件触发后仍能满足容量、时间窗和绿色准入约束的事件比例。

## 8. 评价指标体系

为统一比较 `Q1/Q2/Q3`，建立如下指标体系。所有成本类指标单位统一为元，时间类指标统一为小时，比例类指标以百分比表示。

### 8.1 成本类指标

$$
Z=C_{\text{start}}+C_{\text{energy}}+C_{\text{carbon}}+C_{\text{wait}}+C_{\text{late}}
$$

需要报告：

1. 总成本 $Z$；
2. 固定发车成本 $C_{\text{start}}$；
3. 能耗成本 $C_{\text{energy}}$；
4. 碳成本 $C_{\text{carbon}}$；
5. 等待成本 $C_{\text{wait}}$；
6. 迟到惩罚成本 $C_{\text{late}}$。

若结果分析需要单独报告碳排放量，则使用：

$$
Q^{CO_2}
=
\sum_{m\in M}\sum_{(i,j)\in A}Q_{ijm}^{CO_2}x_{ijm}
$$

其中 $C_{\text{carbon}}=Q^{CO_2}\pi^{CO_2}$。因此，碳成本用于进入目标函数，碳排放量用于环境效果解释，两者不应混为同一个输出。

### 8.2 服务类指标

任务完成率定义为：

$$
R_{\text{task}}=
\frac{\sum_{j\in N^+}\sum_{m\in M}\lambda_{jm}}
{n^+}
$$

若采用 `service_unit` 离散化求解，则可等价按已完成任务单元数除以总任务单元数计算。客户服务率定义为：

需要说明的是，在严格的客户节点层数学模型中，由于已经施加：

$$
\sum_{m\in M}\lambda_{jm}=1,\qquad \forall j\in N^+
$$

只要模型可行，$R_{\text{task}}$ 恒等于 `1`，因此它在理论模型中主要承担可行性门禁作用；真正用于比较方案优劣时，该指标主要适用于启发式执行结果或允许未分配任务的情形。

$$
R_{\text{customer}}=
\frac{|\{j\in N^+\mid \sum_{m\in M}\lambda_{jm}=1\}|}
{n^+}
$$

同时报告未分配任务数、未完全服务客户数和未完成重量 / 体积需求。

### 8.3 时间窗类指标

$$
T_{\text{late}}=\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^-,
\qquad
T_{\text{wait}}=\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^+
$$

进一步报告平均迟到时长、最大迟到时长、迟到客户数和等待总时长。若同一客户被多车拆分服务，则按发生服务的车辆-客户对统计，也可在结果解释中聚合为客户层最大迟到量。

### 8.4 政策类指标

绿色区政策违约次数定义为：

$$
N_{\text{viol}}^{green}
=
\sum_{j\in N^{green}}\sum_{m\in M^{fuel}}
\mathbf{1}\{v_{jm}=1,\ t_{jm}<8\}
$$

在严格施加 GAC 的优化模型中，应有 $N_{\text{viol}}^{green}=0$。此外报告绿色区客户服务完成率、绿色区新能源服务占比、绿色区燃油车延后服务比例和政策增量成本。

### 8.5 动态类指标

动态重优化场景下，报告：

1. 事件响应成功率；
2. 重优化后任务完成率；
3. 动态增量成本 $\Delta Z_3$；
4. 方案扰动幅度 $C_{\text{disrupt}}^{(r)}$ 或对应归一化指标；
5. 事件平均处理时间，即从事件触发到产生新计划的计算时间。

### 8.6 硬约束门禁规则

综合评分之前先执行硬约束门禁：

1. 若容量约束被违反，则方案不可行；
2. 若正需求客户未完成服务且模型未允许弃单，则方案不可行；
3. 若 `Q2/Q3` 政策场景下出现绿色区准入违约，则方案不可行；
4. 若出现路径断裂、车辆未返仓或冻结前缀被回滚，则方案不可行。

只有通过硬约束门禁的方案，才进入成本、服务、时间窗和动态能力的综合评价。

## 9. 敏感性分析设计

敏感性分析不是重新建模，而是在同一模型链上改变关键参数，观察最优路径结构、成本结构和服务质量的变化。

### 9.1 速度水平敏感性

调整拥堵、顺畅、一般三类路况速度均值：

$$
\bar v_p'=(1+\alpha)\bar v_p,\qquad \alpha\in\{-20\%,-10\%,0,10\%,20\%\}
$$

观察总成本、迟到时长、等待时长、车辆启用数量和路径顺序变化。该实验用于检验时变路况对模型结果的影响强度。

### 9.2 绿色区政策敏感性

调整绿色区范围或禁行时间窗，例如：

1. 半径从 `10km` 改为 `8km、12km`；
2. 禁行结束时刻从 `16:00` 改为 `15:00、17:00`；
3. 只限制部分燃油车型或限制全部燃油车型。

观察新能源车使用比例、政策增量成本、绿色区服务完成率和迟到变化。该实验用于评估政策强度对物流成本与服务质量的影响。

### 9.3 罚系数敏感性

调整等待成本和迟到惩罚：

$$
p^{wait'}=\beta_w p^{wait},\qquad
p^{late'}=\beta_l p^{late}
$$

其中 $\beta_w,\beta_l$ 可取 `0.5、1.0、1.5、2.0`。观察模型在低等待、高迟到惩罚等情形下如何改变发车、等待和访问顺序。

### 9.4 车型结构敏感性

调整车辆实例集合 $M$ 中新能源车数量、燃油车数量或大车 / 小车比例，观察：

1. 无政策场景下的成本变化；
2. 绿色区政策场景下的可行性变化；
3. 新能源车辆不足时的迟到与成本上升幅度；
4. 容量结构变化对拆分配送比例 $\lambda_{jm}$ 的影响。

### 9.5 碳价格敏感性

调整碳成本系数 $p_m^{carbon}$，观察燃油车与新能源车的使用结构是否发生转移。该实验用于判断模型结果是否主要由绿色准入硬约束驱动，还是也受到碳成本软约束驱动。

## 10. 问间连接表

| 来源问次 | 传入对象 | 当前问角色 | 传递方式 | 是否继续传出 |
|---|---|---|---|---|
| 问题1 | `x_{ijm}, y_m, \lambda_{jm}, t_{jm}, D_{im}, Z_1` | 问题2的基础路由结构与成本基线 | 在相同客户层输入上追加绿色准入约束后重优化 | 是 |
| 问题1 | `x_{ijm}, q_{ijm}^w, q_{ijm}^v, t_{jm}, D_{im}` | 问题3的初始执行状态 | 转化为车辆当前位置、剩余载荷与已冻结路径前缀 | 是 |
| 问题2 | `G_j, F_m, v_{jm}` | 问题3的政策边界 | 在动态重优化中继续保留绿色准入约束 | 否 |

## 11. 本轮已通过校验

1. 变量分层已清楚区分参数、状态、决策和输出对象。
2. 目标函数与题面动作一致，未把问题强行改写成纯最短路。
3. 约束已覆盖容量、时间窗、路径连续性和政策边界。
4. 问间接口已写清从 `问题1 -> 问题2 -> 问题3` 的传递关系。
5. 已补充每问输出对象、评价指标体系和敏感性分析设计。

## 12. 本轮可疑项

1. 当前正文模型的原始形态是带时变旅行时间和载荷依赖能耗成本的混合整数非线性模型，并非严格 `MILP`。
2. 实际求解采用启发式近似；若论文中要报告严格最优性，需要额外说明分段线性化、离散化口径、终止准则和多次运行稳定性。

## 13. 本轮阻塞项

- 无硬阻塞。
- 已可继续进入结果解释与论文写作层。
