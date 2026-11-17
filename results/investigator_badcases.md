# 调查 Agent 判错案例（测试集，每组最多 10 条）

来源：`results/eval_investigator.json`（prompt v3，2026-11-17 09:26 UTC）。「真值」是 AgentRx 人工标注的根因；「判断」是调查 Agent 的输出。

建议做法：通读后归纳 2-3 类判错原因（例如：选了后面的症状步骤而不是最早的错误；把用户造成的问题算到 agent 头上；类别边界不清），并决定下一轮改什么。

## A 组：trajectory only

| 轨迹 | 真值步骤 | 真值类别 | 判断步骤 | 判断类别 | 错在 |
|---|---|---|---|---|---|
| 3 | 7 | Misinterpretation of Tool Output (assistant) | 34 | Underspecified User Intent (user) | 步骤, 类别 |
| 4 | 15 | Misinterpretation of Tool Output (assistant) | 45 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 21 | 28 | Underspecified User Intent (user) | 41 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 28 | 33 | Intent-Plan Misalignment (assistant) | 33 | Instruction/Plan Adherence Failure (assistant) | 类别 |
| 31 | 31 | Intent-Plan Misalignment (assistant) | 32 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 32 | 11 | Misinterpretation of Tool Output (assistant) | 11 | Invention of New Information (assistant) | 类别 |
| 47 | 19 | Intent Not Supported (assistant) | 18 | Intent Not Supported (user) | 步骤 |
| 63 | 32 | Underspecified User Intent (user) | 23 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 71 | 24 | Underspecified User Intent (user) | 28 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 74 | 21 | Instruction/Plan Adherence Failure (assistant) | 12 | Instruction/Plan Adherence Failure (assistant) | 步骤 |

## B 组：A + outcome check + rule findings

| 轨迹 | 真值步骤 | 真值类别 | 判断步骤 | 判断类别 | 错在 |
|---|---|---|---|---|---|
| 3 | 7 | Misinterpretation of Tool Output (assistant) | 31 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 21 | 28 | Underspecified User Intent (user) | 32 | Underspecified User Intent (user) | 步骤 |
| 28 | 33 | Intent-Plan Misalignment (assistant) | 33 | Instruction/Plan Adherence Failure (assistant) | 类别 |
| 31 | 31 | Intent-Plan Misalignment (assistant) | 32 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 32 | 11 | Misinterpretation of Tool Output (assistant) | 11 | Invention of New Information (assistant) | 类别 |
| 47 | 19 | Intent Not Supported (assistant) | 19 | Instruction/Plan Adherence Failure (assistant) | 类别 |
| 55 | 32 | Underspecified User Intent (user) | 33 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 63 | 32 | Underspecified User Intent (user) | 33 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 71 | 24 | Underspecified User Intent (user) | 27 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 74 | 21 | Instruction/Plan Adherence Failure (assistant) | 12 | Intent-Plan Misalignment (assistant) | 步骤, 类别 |

## C 组：B + verbatim evidence requirement + abstain

| 轨迹 | 真值步骤 | 真值类别 | 判断步骤 | 判断类别 | 错在 |
|---|---|---|---|---|---|
| 21 | 28 | Underspecified User Intent (user) | 40 | Underspecified User Intent (user) | 步骤 （已弃权） |
| 28 | 33 | Intent-Plan Misalignment (assistant) | 33 | Instruction/Plan Adherence Failure (assistant) | 类别 |
| 31 | 31 | Intent-Plan Misalignment (assistant) | 32 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 32 | 11 | Misinterpretation of Tool Output (assistant) | 11 | Invention of New Information (assistant) | 类别 （已弃权） |
| 47 | 19 | Intent Not Supported (assistant) | 17 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 （已弃权） |
| 55 | 32 | Underspecified User Intent (user) | 33 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 63 | 32 | Underspecified User Intent (user) | 33 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 71 | 24 | Underspecified User Intent (user) | 27 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 |
| 74 | 21 | Instruction/Plan Adherence Failure (assistant) | 11 | Intent-Plan Misalignment (assistant) | 步骤, 类别 |
| 79 | 20 | Underspecified User Intent (user) | 23 | Instruction/Plan Adherence Failure (assistant) | 步骤, 类别 （已弃权） |

## C 组判错案例详情

### 轨迹 21  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=21`）
- 标注者：第 28 步 · Underspecified User Intent — At step 28, the user agent insisted on exchange of an item in 'pending' status which is not valid according to domain policy, when assistant asked if it could instead modify (corresponds to the ground truth), the user agent said no.
- 调查 Agent：第 40 步 · Underspecified User Intent · 置信度 0.667 · 已弃权（only 2/3 samples agree on step 40 + Underspecified User Intent） — The user failed to include the shoe exchange item when confirming the order modification, causing the agent to only modify the keyboard and use the wrong payment method.

### 轨迹 28  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=28`）
- 标注者：第 33 步 · Intent Plan Misalignment — At step 33,  the assistant mistakenly believes that it can cancel a subset of a pending order which is not allowed as per domain policy, as a result the entire order got cancelled instead of just the garden hose.
- 调查 Agent：第 33 步 · Instruction/Plan Adherence Failure · 置信度 1.0 — The agent mistakenly cancelled the entire pending order instead of just the garden hose, violating the user's explicit conditional constraint.

### 轨迹 31  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=31`）
- 标注者：第 31 步 · Intent Plan Misalignment — At step 31, the assistant mistakenly believes that it can cancel a subset of a pending order which is not allowed as per domain policy, as a result the entire order got cancelled instead of just the hiking boots.
- 调查 Agent：第 32 步 · Instruction/Plan Adherence Failure · 置信度 1.0 — The agent mistakenly cancelled the entire order containing both the boots and the kettle when the user only wanted to cancel the boot and keep the kettle.

### 轨迹 32  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=32`）
- 标注者：第 11 步 · Misinterpretation of Tool Output — At step 11, the assistant mistakenly provided tracking number of wrong order which did not even contain the tablet.
- 调查 Agent：第 11 步 · Invention of New Information · 置信度 1.0 · 已弃权（no verbatim evidence found at the critical step） — The agent provided the wrong tracking number for the tablet by misidentifying the order details.

### 轨迹 47  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=47`）
- 标注者：第 19 步 · Intent Not Supported — At step 19, the assistant prematurely called transfer to human tool whereas it should have first called the return order tool
- 调查 Agent：第 17 步 · Instruction/Plan Adherence Failure · 置信度 0.667 · 已弃权（only 2/3 samples agree on step 17 + Instruction/Plan Adherence Failure） — The agent failed to execute the return after receiving confirmation and instead re-prompted the user, leading to an unnecessary escalation.

### 轨迹 55  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=55`）
- 标注者：第 32 步 · Underspecified User Intent — The user asked the assistant to return the air purifier, smart watch, and coffee maker while it should have also asked it to return the water bottle from the order according to the task instruction.
- 调查 Agent：第 33 步 · Instruction/Plan Adherence Failure · 置信度 1.0 — The agent failed to include all items intended for return from order #W4597054.

### 轨迹 63  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=63`）
- 标注者：第 32 步 · Underspecified User Intent — In step 32, the user agent asked the assistant to add an item to a pending order instead of replacing it with the cheaper item. This is because of unclear original task instruction.
- 调查 Agent：第 33 步 · Instruction/Plan Adherence Failure · 置信度 1.0 — The agent incorrectly claimed it cannot add new items to an existing order, failing to perform the requested order modification.

### 轨迹 71  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=71`）
- 标注者：第 24 步 · Underspecified User Intent — At step 24, the task instruction did not specify the type of black lamp and since there are multiple black lamps available, it wont be possible to match the ground truth actions.
- 调查 Agent：第 27 步 · Instruction/Plan Adherence Failure · 置信度 1.0 — The agent failed to collect all item modifications before invoking the once-per-order modify items tool, preventing the subsequent modification of the backpack.

### 轨迹 74  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=74`）
- 标注者：第 21 步 · Instruction Adherence Failure — At step 21, the agent called exchange order items tool on an order which is still in pending status which is invalid.
- 调查 Agent：第 11 步 · Intent-Plan Misalignment · 置信度 1.0 — The agent selected a pending order instead of a delivered order for the laptop exchange due to intent-plan misalignment regarding the user's multiple orders.

### 轨迹 79  （`vendor/agentrx/data/tau_retail/tau_dataset_failed.json#task_id=79`）
- 标注者：第 20 步 · Underspecified User Intent — The task instruction did not specify the color of the 1000ml bottle to be exchanged whether it was red or black. Because of this ambiguity, the user agent picked the black bottle whereas the ground truth as the red variant which did not correspond with the ground truth actions. The red variant instead matched the ground truth.
- 调查 Agent：第 23 步 · Instruction/Plan Adherence Failure · 置信度 0.333 · 已弃权（only 1/3 samples agree on step 23 + Instruction/Plan Adherence Failure） — The agent selected the black 1000ml stainless steel water bottle matching the user's statement, but the benchmark expected a different color variant.
