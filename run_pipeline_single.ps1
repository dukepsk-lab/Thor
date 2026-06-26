param([string]$SYMBOL)
Write-Host "Starting pipeline for $SYMBOL..."
python optimize_pipeline.py --symbol $SYMBOL --trials 50 *>&1 | Out-File -FilePath "pipeline_$SYMBOL.log" -Encoding utf8
if ($LASTEXITCODE -ne 0) { exit 1 }
python train_and_save.py --symbol $SYMBOL *>&1 | Out-File -FilePath "pipeline_$SYMBOL.log" -Append -Encoding utf8
if ($LASTEXITCODE -ne 0) { exit 1 }
python backtest_single_symbol.py --symbol $SYMBOL *>&1 | Out-File -FilePath "pipeline_$SYMBOL.log" -Append -Encoding utf8
Write-Host "Pipeline finished for $SYMBOL"
