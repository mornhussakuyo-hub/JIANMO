
直接在终端执行如下命令：

```shell
$env:Q1_ALLOW_VEHICLE_REUSE='1'
$env:Q1_SERVICE_UNIT_MODE='customer_sliced'
$env:Q1_SERVICE_UNIT_TARGET_WEIGHT='750'
$env:Q1_SERVICE_UNIT_TARGET_VOLUME='5.4'
$env:Q1_ALNS_ITERATIONS='2'
$env:Q1_ENABLE_FINAL_BRUTE='0'
python -m src.run_q1
```
