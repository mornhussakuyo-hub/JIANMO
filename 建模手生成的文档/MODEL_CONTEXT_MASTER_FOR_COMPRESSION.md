# 城市绿色物流配送调度模型总上下文主文件

## 0. 文件定位与使用规则

本文件是当前项目在“对话压缩后继续协作”场景下的唯一主上下文文件。

它的用途是：

1. 把已经分散在多个建模文档中的口径合并为一份统一说明；
2. 明确 Q1、Q2、Q3 三问的模型继承关系；
3. 完整保留集合、参数、变量、派生量、目标函数、约束、固定常量、运行时边界和输出口径；
4. 明确数学主模型与程序执行层之间的关系；
5. 吸收最新修订：车辆不再统一固定 `8:00` 发车，而是“最早 `8:00` 发车，实际发车时刻由模型决定”。

本文件整合并覆盖以下来源中的有效内容：

1. [06_model_formulation_pretty(1).md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/06_model_formulation_pretty(1).md)
2. [06_model_formulation_pretty_detailed_explanation.md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/06_model_formulation_pretty_detailed_explanation.md)
3. [07_paper_model_solution_results.md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/07_paper_model_solution_results.md)
4. [q1_tdsdhvrptw_model_for_programmer.md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/q1_tdsdhvrptw_model_for_programmer.md)
5. [q1_tdsdhvrptw_constants_for_programmer.md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/q1_tdsdhvrptw_constants_for_programmer.md)
6. [departure_time_revision_todo.md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/departure_time_revision_todo.md)
7. [departure_time_revision_todo (1).md](D:/华中杯题目/华中杯题目/A题：城市绿色物流配送调度_1776844160973/建模手生成的文档/departure_time_revision_todo%20(1).md)

后续若旧文档与本文件冲突，按以下优先级处理：

1. 涉及 `D_{0m}` 发车时刻口径时，以本文件为准；
2. 涉及 Q1/Q2/Q3 继承关系时，以本文件为准；
3. 涉及常量、单位、输出字段时，以本文件为准；
4. 涉及程序层 `service_unit` 与数学主模型客户层关系时，以本文件为准。

补充说明：

1. `departure_time_revision_todo (1).md` 没有再引入新的模型机制；
2. 它主要补充了“哪些文件已经完成同步”的执行状态说明；
3. 同时把若干公式写法从 `Ty_m` 统一成更规范的 `T y_m`；
4. 因此当前最新有效口径仍然是“可变发车时刻 + 首段按 `D_{0m}` 传播”，这一点本文件已完整吸收。

## 1. 整题模型主线

整题按如下递进链组织：

$$
\text{TDSDHVRPTW}
\rightarrow
\text{TDSDHVRPTW-GAC}
\rightarrow
\text{Dynamic TDSDHVRPTW}
$$

分别对应：

1. Q1：静态基线调度模型；
2. Q2：在 Q1 基础上加入绿色准入约束；
3. Q3：在 Q1/Q2 的状态基础上加入动态事件与滚动重优化。

其中：

- `TD`：Time-Dependent，行驶时间依赖出发时刻；
- `SD`：Split Delivery，客户允许拆分配送；
- `H`：Heterogeneous Fleet，异构车队；
- `VRPTW`：Vehicle Routing Problem with Time Windows，带时间窗车辆路径问题；
- `GAC`：Green Access Constraint，绿色准入约束。

## 2. 业务问题本质

本题不是普通 CVRP，而是同时包含以下因素的复杂路径优化问题：

1. 单配送中心；
2. 多客户节点；
3. 异构车队；
4. 重量与体积双容量约束；
5. 软时间窗；
6. 时变旅行时间；
7. 速度相关能耗；
8. 载重相关能耗修正；
9. 碳排放成本；
10. 绿色准入政策；
11. 动态事件重优化。

因此：

1. 数学主模型不是简单线性 VRP；
2. 程序层不宜追求直接精确全局最优；
3. 实现上更适合“精确路线评价器 + 启发式/ALNS/局部搜索”。

## 3. 数学主模型与程序执行层的关系

这一点必须严格区分。

### 3.1 数学主模型

Q1 数学主模型是在“客户层”建模。

即：

1. 每个客户 `j` 有聚合后的重量需求 `W_j` 和体积需求 `V_j`；
2. 是否由车辆 `m` 服务、服务多少比例，由 `\lambda_{jm}` 描述；
3. 主模型不直接把每条原始订单当作独立决策单元。

### 3.2 程序执行层

程序层允许把客户需求进一步拆成离散任务块：

- `service_unit`

这个对象只属于求解器执行层，不改变数学主模型。

它的作用是：

1. 方便构造初始解；
2. 方便插入、交换、relocate、2-opt 等邻域操作；
3. 便于在启发式中处理超大客户和拆分配送。

最终程序输出应能聚合回客户层变量：

$$
\lambda_{jm},\qquad
\delta_{jm}^{w}=\lambda_{jm}W_j,\qquad
\delta_{jm}^{v}=\lambda_{jm}V_j
$$

## 4. Q1 统一假设

### 4.1 基础假设

1. 研究对象是单日静态配送；
2. 所有车辆从唯一配送中心 `0` 出发并最终返仓；
3. Q1 只对正需求客户建模；
4. 订单在清洗阶段已聚合到客户层；
5. 允许拆分配送；
6. 不考虑途中加油、充电和补能设施选址；
7. 数学主模型按单趟单回路刻画；
8. 代码层若复用车辆跑多趟，属于执行层扩展，不属于当前数学主模型。

### 4.2 时间口径假设

1. 全部数学时间变量以 `8:00` 为零点；
2. 数学文档中通常用“相对 `8:00` 的小时数”；
3. 程序层允许用“当天绝对分钟”实现；
4. 若程序层用分钟，则输出或解释时必须明确换算；
5. 客户固定服务时间为 `20 min`。

### 4.3 发车时刻修订后的统一口径

这是最新修订，必须覆盖所有旧版“固定 8:00 发车”说法。

旧口径：

$$
D_{0m}=0
$$

现统一修订为：

$$
0\le D_{0m}\le T y_m,\qquad \forall m\in M
$$

其含义是：

1. `0` 表示 `8:00`；
2. 车辆不得早于 `8:00` 发车；
3. 若 `y_m=0`，则 `D_{0m}=0`；
4. 若 `y_m=1`，则 `D_{0m}` 是车辆 `m` 的实际发车时刻；
5. 实际发车时刻由模型根据时间窗、时变路况和成本共同决定。

因此：

1. 所有车辆不再强制同一时刻发车；
2. 首段时间传播必须按 `D_{0m}` 计算；
3. 路线输出里的首段 `depart_time` 不再固定等于 `8:00`。

### 4.4 时变速度假设

1. 题面给的是不同路况下的随机速度分布；
2. Q1 采用均值确定化；
3. 旅行时间必须用分段累计；
4. 弧段若跨多个时段，不能只取出发瞬间速度粗略估算；
5. 超出显式规划时段后，按中速外推。

### 4.5 拆分配送假设

1. 同一客户可由多辆车共同服务；
2. 重量与体积按同一比例拆分；
3. 程序层可再离散为多个 `service_unit`；
4. 最终输出仍应能还原到客户层比例变量。

### 4.6 能耗假设

1. 能耗受速度影响；
2. 能耗受重量装载率影响；
3. 体积只用于容量约束，不进入能耗修正；
4. 碳成本由能耗乘以碳排因子和碳价得到。

## 5. 集合定义

| 符号 | 含义 |
|---|---|
| $N$ | 全体客户集合 |
| $N^+$ | 正需求客户集合 |
| $n^+=|N^+|$ | 正需求客户数量 |
| $V=\{0\}\cup N^+$ | 节点集合，0 为配送中心 |
| $A=\{(i,j)\mid i,j\in V,\ i\neq j\}$ | 有向弧集合 |
| $K=\{1,2,3,4,5\}$ | 车型集合 |
| $M$ | 车辆实例集合 |
| $M^{fuel}$ | 燃油车实例集合 |
| $M^{elec}$ | 新能源车实例集合 |
| $N^{green}$ | 正需求绿色区客户集合，Q2 使用 |
| $\mathcal P$ | 路况时段集合 |
| $\mathcal H=[0,T]$ | 规划时间域 |

并有：

$$
M=M^{fuel}\cup M^{elec},\qquad
M^{fuel}\cap M^{elec}=\varnothing
$$

当前数据口径下：

1. 全体客户数为 `98`；
2. 正需求客户数为 `88`；
3. 绿色区客户数在清洗后坐标规则下与题面“30 个”文字不完全一致，程序与建模应以当前清洗口径为准，而不是强行沿用题面文字。

## 6. 输入参数

### 6.1 客户参数

| 符号 | 含义 |
|---|---|
| $W_j$ | 客户 `j` 的聚合重量需求 |
| $V_j$ | 客户 `j` 的聚合体积需求 |
| $e_j$ | 客户 `j` 最早服务时刻 |
| $l_j$ | 客户 `j` 最晚服务时刻 |
| $s_j$ | 客户 `j` 服务时间 |
| $G_j$ | 客户 `j` 是否属于绿色区，Q2 起使用 |

### 6.2 车辆参数

| 符号 | 含义 |
|---|---|
| $Q_m^w$ | 车辆 `m` 最大载重 |
| $Q_m^v$ | 车辆 `m` 最大容积 |
| $f_m$ | 车辆 `m` 启动成本 |
| $e(m)$ | 车辆 `m` 的能源类型 |
| $\kappa(m)$ | 车辆 `m` 所属车型编号 |

### 6.3 距离参数

| 符号 | 含义 |
|---|---|
| $d_{ij}$ | 节点 `i` 到节点 `j` 的道路距离 |

### 6.4 交通参数

| 符号 | 含义 |
|---|---|
| $\bar v_p$ | 路况时段 `p` 的期望速度 |

### 6.5 能源与碳参数

| 符号 | 含义 |
|---|---|
| $p_m^{energy}$ | 单位能源价格 |
| $\eta_m^{CO_2}$ | 单位能源碳排放因子 |
| $\pi^{CO_2}$ | 单位碳价格 |
| $p_m^{carbon}$ | 单位能源对应的碳成本系数 |

### 6.6 成本与边界参数

| 符号 | 含义 |
|---|---|
| $p^{wait}$ | 等待成本单价 |
| $p^{late}$ | 迟到惩罚单价 |
| $T$ | 规划时间域上界 |
| $\Omega$ | 大常数 |

## 7. 决策变量

| 变量 | 类型 | 含义 |
|---|---|---|
| $x_{ijm}$ | 0-1 | 车辆 `m` 是否走弧 `(i,j)` |
| $y_m$ | 0-1 | 车辆 `m` 是否启用 |
| $\lambda_{jm}$ | 连续 | 车辆 `m` 承担客户 `j` 的需求比例 |
| $q_{ijm}^w$ | 连续 | 弧 `(i,j)` 上的剩余重量载荷 |
| $q_{ijm}^v$ | 连续 | 弧 `(i,j)` 上的剩余体积载荷 |
| $t_{jm}$ | 连续 | 车辆 `m` 到达客户 `j` 的时刻 |
| $D_{im}$ | 连续 | 车辆 `m` 离开节点 `i` 的时刻 |
| $D_{0m}$ | 连续 | 车辆 `m` 从配送中心实际发车时刻 |
| $T_m^{ret}$ | 连续 | 车辆 `m` 返回配送中心的时刻 |
| $\varepsilon_{jm}^{+}$ | 连续 | 等待量 |
| $\varepsilon_{jm}^{-}$ | 连续 | 迟到量 |
| $u_{jm}$ | 连续 | MTZ 顺序变量 |

## 8. 派生量

| 派生量 | 定义 | 含义 |
|---|---|---|
| $v_{jm}$ | $\sum_{i\in V,i\neq j}x_{ijm}$ | 车辆 `m` 是否访问客户 `j` |
| $\delta_{jm}^{w}$ | $\lambda_{jm}W_j$ | 实际配送重量 |
| $\delta_{jm}^{v}$ | $\lambda_{jm}V_j$ | 实际配送体积 |
| $\rho_{ijm}$ | $q_{ijm}^w/Q_m^w$ | 弧段装载率 |
| $d_{ij}^{(p)}(t)$ | 分段距离份额 | 在时段 `p` 内完成的距离 |
| $E_{ijm}(D_{im},\rho_{ijm})$ | 弧段能耗 | 实际能耗量 |
| $Q_{ijm}^{CO_2}$ | $E_{ijm}\eta_m^{CO_2}$ | 碳排放量 |
| $c_{ijm}^{energy}$ | $E_{ijm}p_m^{energy}$ | 能耗成本 |
| $c_{ijm}^{carbon}$ | $Q_{ijm}^{CO_2}\pi^{CO_2}$ | 碳成本 |

## 9. 固定常量与程序口径

### 9.1 时间常量

| 名称 | 数值 |
|---|---:|
| `time_origin` | `08:00` |
| `service_start_min` | `480` |
| `hour_to_min` | `60` |
| `service_time_min` | `20` |
| $s_j$ | $1/3$ 小时 |
| $s_0$ | `0` |

### 9.2 速度时段常量

| 标签 | 相对时间区间 | 绝对时间区间 | 速度 km/h |
|---|---|---|---:|
| C | $[0,1)$ | 08:00-09:00 | 9.8 |
| S | $[1,2)$ | 09:00-10:00 | 55.3 |
| N | $[2,3.5)$ | 10:00-11:30 | 35.4 |
| C | $[3.5,5)$ | 11:30-13:00 | 9.8 |
| S | $[5,7)$ | 13:00-15:00 | 55.3 |
| N | $[7,9)$ | 15:00-17:00 | 35.4 |
| N | $[9,+\infty)$ | 17:00 以后 | 35.4 |

程序配置建议：

```text
speed_segments = [
  (480, 540, 9.8),
  (540, 600, 55.3),
  (600, 690, 35.4),
  (690, 780, 9.8),
  (780, 900, 55.3),
  (900, 1020, 35.4)
]
fallback_speed_kmh = 35.4
```

### 9.3 能耗函数常量

燃油车：

$$
FPK(v)=0.0025v^2-0.2554v+31.75
$$

新能源车：

$$
EPK(v)=0.0014v^2-0.12v+36.19
$$

### 9.4 装载修正常量

$$
\phi^{fuel}(\rho)=1+0.4\rho,\qquad
\phi^{new}(\rho)=1+0.35\rho
$$

### 9.5 能源价格、碳因子与碳价

| 名称 | 数值 |
|---|---:|
| `fuel_price` | 7.61 |
| `electricity_price` | 1.64 |
| `fuel_carbon_factor` | 2.547 |
| `electric_carbon_factor` | 0.501 |
| `carbon_price` | 0.65 |

### 9.6 成本常量

| 名称 | 数值 |
|---|---:|
| `startup_cost` | 400 |
| `wait_cost_per_hour` | 20 |
| `late_cost_per_hour` | 50 |

注意：

若代码里等待和迟到用“分钟”存储，则计算成本时必须先除以 `60`。

### 9.7 车型固定输入表

| 车型 | 能源类型 | 载重 kg | 容积 m^3 | 数量 | 启动成本 |
|---:|---|---:|---:|---:|---:|
| 1 | 燃油 | 3000 | 13.5 | 60 | 400 |
| 2 | 燃油 | 1500 | 10.8 | 50 | 400 |
| 3 | 燃油 | 1250 | 6.5 | 50 | 400 |
| 4 | 新能源 | 3000 | 15.0 | 10 | 400 |
| 5 | 新能源 | 1250 | 8.5 | 15 | 400 |

### 9.8 运行时派生量

这些量不应固定硬编码，而应随输入数据运行时生成：

1. $N^+$；
2. $n^+$；
3. $M$；
4. $A$；
5. $T$；
6. `big_m_time`；
7. `big_m_order`。

## 10. 时间依赖旅行时间函数

数学定义：

$$
\tau_{ij}(t)=\inf\left\{\Delta\ge 0:\int_t^{t+\Delta}v(u)\,du\ge d_{ij}\right\}
$$

实现原则：

1. 从出发时刻 `t` 开始；
2. 找到当前所属交通时段；
3. 计算当前时段剩余可行驶时间；
4. 计算该时段最多可行驶距离；
5. 若剩余距离在本时段内可完成，则结束；
6. 否则进入下一时段继续推进；
7. 同时记录各时段完成的距离份额 `d_{ij}^{(p)}(t)`。

最稳的程序做法是：

1. 先生成 `travel_segments`；
2. 再由片段求和得到总旅行时间；
3. 同一片段结果同时用于能耗计算。

## 11. 能耗与碳排计算

### 11.1 装载率

$$
\rho_{ijm}=\frac{q_{ijm}^w}{Q_m^w}
$$

### 11.2 单位里程能耗率

燃油车：

$$
\psi_m(v,\rho)=FPK(v)\phi^{fuel}(\rho)
$$

新能源车：

$$
\psi_m(v,\rho)=EPK(v)\phi^{new}(\rho)
$$

### 11.3 弧段能耗

$$
E_{ijm}(D_{im},\rho_{ijm})=
\begin{cases}
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}FPK(\bar v_p)\phi^{fuel}(\rho_{ijm}), & m\in M^{fuel}\\
\sum\limits_{p\in\mathcal P}\dfrac{d_{ij}^{(p)}(D_{im})}{100}EPK(\bar v_p)\phi^{new}(\rho_{ijm}), & m\in M^{elec}
\end{cases}
$$

### 11.4 能耗、碳排与成本

$$
c_{ijm}^{energy}=E_{ijm}(D_{im},\rho_{ijm})p_m^{energy}
$$

$$
Q_{ijm}^{CO_2}=E_{ijm}(D_{im},\rho_{ijm})\eta_m^{CO_2}
$$

$$
c_{ijm}^{carbon}=Q_{ijm}^{CO_2}\pi^{CO_2}
$$

## 12. Q1 目标函数

$$
\min Z_1=C_{start}+C_{energy}+C_{carbon}+C_{wait}+C_{late}
$$

其中：

$$
C_{start}=\sum_{m\in M}f_my_m
$$

$$
C_{energy}=\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{energy}x_{ijm}
$$

$$
C_{carbon}=\sum_{m\in M}\sum_{(i,j)\in A}c_{ijm}^{carbon}x_{ijm}
$$

$$
C_{wait}=p^{wait}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^{+}
$$

$$
C_{late}=p^{late}\sum_{j\in N^+}\sum_{m\in M}\varepsilon_{jm}^{-}
$$

## 13. Q1 约束体系

### 13.1 需求满足

$$
\sum_{m\in M}\lambda_{jm}=1,\qquad \forall j\in N^+
$$

### 13.2 访问与拆分联动

$$
v_{jm}=\sum_{i\in V,i\neq j}x_{ijm}
$$

$$
0\le \lambda_{jm}\le v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

### 13.3 路径连续

$$
\sum_{i\in V,i\neq j}x_{ijm}
=
\sum_{l\in V,l\neq j}x_{jlm}
\le 1,\qquad \forall j\in N^+,\forall m\in M
$$

### 13.4 车辆启用与闭环

$$
\sum_{j\in N^+}x_{0jm}=y_m,\qquad
\sum_{i\in N^+}x_{i0m}=y_m,\qquad \forall m\in M
$$

$$
v_{jm}\le y_m,\qquad \forall j\in N^+,\forall m\in M
$$

### 13.5 载荷流守恒

重量：

$$
\sum_{i\in V,i\neq j}q_{ijm}^{w}
-\sum_{l\in V,l\neq j}q_{jlm}^{w}
=\lambda_{jm}W_j
$$

体积：

$$
\sum_{i\in V,i\neq j}q_{ijm}^{v}
-\sum_{l\in V,l\neq j}q_{jlm}^{v}
=\lambda_{jm}V_j
$$

出仓总装载量：

$$
\sum_{j\in N^+}q_{0jm}^{w}
=
\sum_{j\in N^+}\lambda_{jm}W_j
$$

$$
\sum_{j\in N^+}q_{0jm}^{v}
=
\sum_{j\in N^+}\lambda_{jm}V_j
$$

返仓空载：

$$
\sum_{i\in N^+}q_{i0m}^{w}=0,\qquad
\sum_{i\in N^+}q_{i0m}^{v}=0,\qquad \forall m\in M
$$

### 13.6 容量约束

$$
0\le q_{ijm}^{w}\le Q_m^{w}x_{ijm}
$$

$$
0\le q_{ijm}^{v}\le Q_m^{v}x_{ijm}
$$

### 13.7 离开时刻定义

客户节点：

$$
D_{jm}=t_{jm}+\varepsilon_{jm}^{+}+s_jv_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

配送中心发车时刻：

$$
0\le D_{0m}\le Ty_m,\qquad \forall m\in M
$$

### 13.8 时间传播约束

首段传播修订后统一写法：

$$
t_{jm}\ge D_{0m}+\tau_{0j}(D_{0m})-\Omega(1-x_{0jm}),\qquad \forall j\in N^+,\forall m\in M
$$

客户到客户：

$$
t_{jm}\ge D_{im}+\tau_{ij}(D_{im})-\Omega(1-x_{ijm}),\qquad \forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

返仓：

$$
T_m^{ret}\ge D_{im}+\tau_{i0}(D_{im})-\Omega(1-x_{i0m}),\qquad \forall i\in N^+,\forall m\in M
$$

如需严格绑定最后返仓弧，还可加：

$$
T_m^{ret}\le D_{im}+\tau_{i0}(D_{im})+\Omega(1-x_{i0m}),\qquad \forall i\in N^+,\forall m\in M
$$

并有：

$$
T_m^{ret}\le Ty_m,\qquad \forall m\in M
$$

### 13.9 软时间窗

等待量：

$$
\varepsilon_{jm}^{+}\ge e_j-t_{jm}-\Omega(1-v_{jm}),\qquad \forall j\in N^+,\forall m\in M
$$

迟到量：

$$
\varepsilon_{jm}^{-}\ge t_{jm}-l_j-\Omega(1-v_{jm}),\qquad \forall j\in N^+,\forall m\in M
$$

关闭未访问节点时间变量：

$$
t_{jm},D_{jm},\varepsilon_{jm}^{+},\varepsilon_{jm}^{-}\le \Omega v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

注意当前统一解释：

1. 等待量来自“实际到达时刻”与时间窗起点的比较；
2. 在可变发车时刻设定下，不再把等待统一归因为固定 `8:00` 发车。

### 13.10 子回路消除

$$
0\le u_{jm}\le n^+v_{jm},\qquad \forall j\in N^+,\forall m\in M
$$

$$
u_{im}-u_{jm}+n^+x_{ijm}\le n^+-1,\qquad \forall i,j\in N^+,\ i\neq j,\forall m\in M
$$

### 13.11 变量域

$$
x_{ijm},y_m\in\{0,1\},\qquad 0\le \lambda_{jm}\le 1
$$

$$
q_{ijm}^{w},q_{ijm}^{v},t_{jm},D_{im},T_m^{ret},
\varepsilon_{jm}^{+},\varepsilon_{jm}^{-},u_{jm}\ge 0
$$

且已单独补充：

$$
0\le D_{0m}\le Ty_m
$$

## 14. Q1 模型类型判断

Q1 原始模型不是严格线性 MILP，原因是：

1. `\tau_{ij}(D_{im})` 依赖决策变量 `D_{im}`；
2. `E_{ijm}(D_{im},\rho_{ijm})` 依赖 `D_{im}` 和 `q_{ijm}^w`；
3. 能源成本与碳成本不是固定边权。

因此更准确的说法是：

- 带时变旅行时间和载荷依赖成本的混合整数非线性车辆路径模型。

程序层应采用：

1. 分段实时计算；
2. 查表近似；
3. 或启发式算法求近似解。

## 15. Q1 程序实现建议

### 15.1 数据准备

1. 读取客户数据；
2. 过滤出正需求客户；
3. 读取车型和车辆实例；
4. 读取距离矩阵；
5. 生成运行时边界；
6. 保持“数学层客户对象”和“执行层 service_unit”两层结构。

### 15.2 service_unit 离散化

建议规则：

1. 超单车容量客户必须拆分；
2. 普通客户可保留一个任务块；
3. 若启发式需要，也可进一步切成多个任务块；
4. 所有任务块都要能映射回原客户。

### 15.3 统一核心模块

后续所有求解器都应围绕三大底层模块组织：

1. `traffic.py`
2. `costs.py`
3. `route_evaluator.py`

其中 `route_evaluator.py` 是 Q1、Q2、Q3 共同的核心评价器。

### 15.4 推荐求解算法

最稳的路线是：

1. `service_unit` 离散化；
2. 初始解构造；
3. `relocate/swap/2-opt` 局部搜索；
4. 进一步升级到 ALNS。

也可以采用：

1. 贪心插入 + 局部搜索；
2. ALNS；
3. Beam Search 初始解 + ALNS。

不建议第一版直接做端到端神经网络求解。

## 16. Q2 继承关系

Q2 完整继承 Q1 的变量、参数、成本和约束结构，仅新增绿色准入约束：

$$
t_{jm}\ge 8-\Omega(1-v_{jm}),\qquad \forall j\in N^{green},\forall m\in M^{fuel}
$$

这里的 `8` 表示相对 `8:00` 的小时数，即 `16:00`。

注意：

1. Q2 不重写目标函数；
2. Q2 继续继承最新的“可变发车时刻”口径；
3. Q2 的改变只在于收紧可行域，而非改写成本结构。

## 17. Q3 继承关系

Q3 继承 Q1/Q2 的成本与约束结构，但在状态层增加：

1. 车辆当前位置；
2. 车辆可用时刻；
3. 车辆剩余载荷；
4. 已完成客户；
5. 部分完成客户；
6. 剩余待服务客户；
7. 已冻结前缀；
8. 原计划剩余后缀；
9. 新增事件集合。

动态状态对象可写为：

$$
\mathcal S(t_r)=
\big(
M^{act}(t_r),
N^{done}(t_r),
N^{part}(t_r),
N^{todo}(t_r),
\bar W(t_r),
\bar V(t_r),
N^{new}(t_r),
\Pi^{fix}(t_r),
\Pi^{old,rem}(t_r)
\big)
$$

Q3 核心思想：

1. 冻结已执行前缀；
2. 更新车辆当前状态；
3. 对剩余任务做滚动重优化；
4. 通过扰动成本控制新旧方案偏离程度。

## 18. 输出口径

### 18.1 路线弧段表

至少应包含：

1. `vehicle_id`
2. `route_id`
3. `sequence`
4. `from_node`
5. `to_node`
6. `distance_km`
7. `depart_time`
8. `arrival_time`
9. `service_start_time`
10. `service_end_time`
11. `load_weight`
12. `load_volume`
13. `load_ratio`
14. `travel_time`
15. `energy_amount`
16. `energy_cost`
17. `co2_amount`
18. `carbon_cost`
19. `wait_time`
20. `late_time`

特别注意：

若 `from_node = 0`，则 `depart_time` 对应的是实际发车时刻 `D_{0m}`，不能再默认写成固定 `8:00`。

### 18.2 客户服务表

至少应包含：

1. `customer_id`
2. `vehicle_id`
3. `visit_flag`
4. `lambda`
5. `served_weight`
6. `served_volume`
7. `arrival_time`
8. `service_start_time`
9. `service_end_time`
10. `wait_time`
11. `late_time`

### 18.3 车辆汇总表

至少应包含：

1. `vehicle_id`
2. `used`
3. `return_time`
4. `route_distance`
5. `route_fixed_cost`
6. `route_energy_cost`
7. `route_carbon_cost`
8. `route_wait_cost`
9. `route_late_cost`
10. `route_total_cost`

### 18.4 KPI 汇总表

至少应包含：

1. `total_cost`
2. `fixed_cost`
3. `energy_cost`
4. `carbon_cost`
5. `wait_cost`
6. `late_cost`
7. `total_distance`
8. `used_vehicle_count`
9. `served_customer_count`
10. `unassigned_task_count`
11. `total_co2`

## 19. 统一可行性检查建议

程序层应统一检查以下内容：

1. 初始总重量不超车型容量；
2. 初始总体积不超车型容量；
3. stop、service_unit、customer 三者编号一致；
4. 距离矩阵完整；
5. 行驶分段合法；
6. 能耗、碳成本非负；
7. 卸货后剩余载荷不为负；
8. 返仓前理论应空载；
9. 客户需求全部被服务；
10. Q2 下绿色准入无违约；
11. Q3 下冻结前缀不被回滚。

## 20. 最容易出错的口径

后续继续写文档或代码时，最容易犯错的是：

1. 把旧版 `D_{0m}=0` 又写回来；
2. 把 Q2 绿色约束混进 Q1；
3. 把客户层数学模型和 `service_unit` 程序层混为一谈；
4. 用局部边增量替代完整路线重算；
5. 代码里用“绝对分钟”，解释里忘了换成“相对 8:00 小时”；
6. 等待/迟到按分钟存储时，算成本忘记除以 `60`；
7. 路线输出表里首段 `depart_time` 仍写成固定 `8:00`。

## 21. 推荐最终标准表述

后续无论写论文、队内交接还是继续编程，关于发车时间统一使用下述表述：

> 本文以 `8:00` 作为配送计划起点，所有时间变量均以 `8:00` 为零点。车辆不得早于 `8:00` 从配送中心出发；启用车辆的实际发车时刻 $D_{0m}$ 由模型根据客户时间窗、时变路况和成本目标决定。每个启用车辆实例执行一条从配送中心出发并最终返回配送中心的闭合路径。

## 22. 压缩上下文时的保留建议

如果后续对话需要压缩，请优先保留本文件中的以下内容：

1. Q1/Q2/Q3 三问总链；
2. `D_{0m}` 修订后的统一口径；
3. Q1 全部集合、参数、变量、目标与约束；
4. 固定常量；
5. 数学主模型与 `service_unit` 执行层的关系；
6. Q2 和 Q3 的继承方式；
7. 输出字段和程序可行性检查。

若只能保留一句最关键总结，则保留：

> Q1 的数学主模型是客户层的 TDSDHVRPTW，车辆最早 `8:00` 发车但实际发车时刻 `D_{0m}` 由模型决定；程序层可用 `service_unit` 离散化并通过精确路线评价器配合启发式求解，Q2 在此基础上增加绿色准入，Q3 在此基础上做冻结前缀和滚动重优化。
