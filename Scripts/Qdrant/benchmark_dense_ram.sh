#!/usr/bin/env bash
# Measure Qdrant only, using existing embeddings; no model or index build.
set -euo pipefail

container=${1:-sbtc-qdrant}
collection=${2:-sbtc_gte_multilingual}
output=${3:?Usage: benchmark_dense_ram.sh CONTAINER COLLECTION NEW_OUTPUT_DIR}
base=http://127.0.0.1:6333
count=50
mkdir "$output"
output=$(realpath "$output")
mkdir "$output/queries"

curl -fsS "$base/collections/$collection" > "$output/collection-before.json"
docker inspect "$container" > "$output/container.json"
free -b > "$output/host-memory-before.txt"
lscpu > "$output/host-cpu.txt"
uname -a > "$output/host-kernel.txt"

# Random UUID point order gives a reproducible, varied sample without corpus text.
curl -fsS --max-time 120 -X POST "$base/collections/$collection/points/scroll" \
  -H 'Content-Type: application/json' \
  -d "{\"limit\":$count,\"with_vector\":true,\"with_payload\":false}" \
  > "$output/query-points.json"
jq -e --argjson n "$count" '.result.points | length == $n' "$output/query-points.json" >/dev/null
jq -c '.result.points[] | {point_id:.id,query:.vector}' "$output/query-points.json" \
  > "$output/query-vectors.jsonl"
sha256sum "$output/query-vectors.jsonl" > "$output/query-vectors.sha256"

cat > "$output/request.sh" <<'REQUEST'
#!/usr/bin/env bash
set -euo pipefail
index=$1
query=$(( (index-1)%50+1 ))
target="$RUN_OUTPUT/response-$index.json"
elapsed=$(curl -fsS --max-time 180 -X POST "$QUERY_URL" \
  -H 'Content-Type: application/json' --data-binary "@$QUERY_DIR/$query.json" \
  -o "$target" -w '%{time_total}')
jq -ce --argjson elapsed "$elapsed" --argjson index "$index" --argjson k "$TOP_K" \
  'if .status != "ok" or (.result.points | length) != $k then error("incomplete query")
   else {request:$index,wall_seconds:$elapsed,server_seconds:.time,
         returned:(.result.points|length)} end' "$target" > "$RUN_OUTPUT/timing-$index.json"
REQUEST
chmod +x "$output/request.sh"

sample_memory() {
  local process=$1 cgroup=$2 target=$3
  printf 'epoch_seconds,rss_kib,rss_anon_kib,rss_file_kib,rss_shmem_kib,process_swap_kib,cgroup_bytes,cgroup_anon_bytes,cgroup_file_bytes,cgroup_kernel_bytes,host_available_kib,host_swap_used_kib\n' > "$target"
  while true; do
    awk -v now="$(date +%s.%N)" '
      FILENAME ~ /\/status$/ {
        if ($1=="VmRSS:") rss=$2; if ($1=="RssAnon:") anon=$2;
        if ($1=="RssFile:") file=$2; if ($1=="RssShmem:") shared=$2;
        if ($1=="VmSwap:") swap=$2
      }
      FILENAME ~ /memory.current$/ {current=$1}
      FILENAME ~ /memory.stat$/ {
        if ($1=="anon") ca=$2; if ($1=="file") cf=$2; if ($1=="kernel") ck=$2
      }
      FILENAME ~ /meminfo$/ {
        if ($1=="MemAvailable:") avail=$2; if ($1=="SwapTotal:") st=$2;
        if ($1=="SwapFree:") sf=$2
      }
      END {printf "%s,%d,%d,%d,%d,%d,%.0f,%.0f,%.0f,%.0f,%d,%d\n",now,rss,anon,file,shared,swap,current,ca,cf,ck,avail,st-sf}
    ' "/proc/$process/status" "$cgroup/memory.current" "$cgroup/memory.stat" /proc/meminfo >> "$target"
    sleep 0.1
  done
}

sampler=''
trap 'if [[ -n "$sampler" ]]; then kill "$sampler" 2>/dev/null || true; wait "$sampler" 2>/dev/null || true; fi' EXIT
export QUERY_URL="$base/collections/$collection/points/query" QUERY_DIR="$output/queries"
for top_k in 20 1000; do
  for concurrency in 1 4; do
    docker restart "$container" > /dev/null
    ready=false
    for attempt in $(seq 1 120); do
      if curl -fsS "$base/readyz" > /dev/null 2>&1; then ready=true; break; fi
      sleep 1
    done
    [[ $ready == true ]]
    sleep 5
    process=$(docker top "$container" -eo pid,comm | awk '$2=="qdrant" {print $1}')
    [[ -n "$process" ]]
    cgroup_path=$(awk -F: '$1=="0" {print $3}' "/proc/$process/cgroup")
    cgroup="/sys/fs/cgroup$cgroup_path"
    index=0
    while IFS= read -r vector; do
      index=$((index+1))
      jq -c --argjson k "$top_k" '{query:.query,limit:$k,with_payload:false,with_vector:false,params:{hnsw_ef:128,exact:false}}' \
        <<< "$vector" > "$output/queries/$index.json"
    done < "$output/query-vectors.jsonl"
    for phase in first_pass repeated; do
      run="$output/k${top_k}-c${concurrency}-${phase}"
      mkdir "$run"
      export RUN_OUTPUT="$run" TOP_K="$top_k"
      cat "$cgroup/memory.events" > "$run/memory-events-before.txt"
      sample_memory "$process" "$cgroup" "$run/memory.csv" &
      sampler=$!
      sleep 1
      requests=$count
      [[ $phase != repeated ]] || requests=$((count*2))
      start=$(date +%s.%N)
      seq 1 "$requests" | xargs -P "$concurrency" -n 1 "$output/request.sh"
      end=$(date +%s.%N)
      sleep 1
      kill "$sampler"
      wait "$sampler" 2>/dev/null || true
      sampler=''
      cat "$cgroup/memory.events" > "$run/memory-events-after.txt"
      cat "/proc/$process/status" > "$run/process-status-after.txt"
      jq -s --argjson k "$top_k" --argjson concurrency "$concurrency" \
        --arg phase "$phase" --argjson start "$start" --argjson end "$end" \
        'sort_by(.wall_seconds) | {top_k:$k,concurrency:$concurrency,phase:$phase,
          queries:length,wall_seconds:($end-$start),qps:(length/($end-$start)),
          p50_seconds:.[(length*0.50|floor)].wall_seconds,
          p95_seconds:.[(length*0.95|ceil)-1].wall_seconds,
          max_seconds:.[-1].wall_seconds,errors:0}' \
        "$run"/timing-*.json > "$run/latency.json"
      cat "$run/latency.json"
    done
  done
done
curl -fsS "$base/collections/$collection" > "$output/collection-after.json"
free -b > "$output/host-memory-after.txt"
printf '%s\n' 'Database-only benchmark; 50 stored dense vectors, each includes a possible self match.' \
  '50 first-pass requests, then 100 repeated requests per top-k/concurrency combination.' \
  'Process restarted per combination; OS page cache retained. First pass is not cold-disk.' \
  'Top-k 20 and 1000; concurrency 1 and 4; HNSW ef=128; no payload hydration.' \
  'Memory sampled approximately every 100 ms; short spikes may be missed.' \
  'RSS includes mapped file pages; cgroup file includes reclaimable page cache.' \
  'Excludes embedding model and application pipeline. Lexical/hybrid deferred by user.' > "$output/LIMITATIONS.txt"
for run in "$output"/k*-c*; do
  jq -Rn '[inputs | split(",") | map(tonumber? // .)] | .[1:] |
    {memory_samples:length,baseline_rss_kib:.[0][1],
     peak_rss_kib:(map(.[1])|max),peak_anon_kib:(map(.[2])|max),
     peak_mapped_file_kib:(map(.[3])|max),peak_swap_kib:(map(.[5])|max),
     baseline_cgroup_bytes:.[0][6],peak_cgroup_bytes:(map(.[6])|max),
     peak_cgroup_file_bytes:(map(.[8])|max),
     min_host_available_kib:(map(.[10])|min),peak_host_swap_used_kib:(map(.[11])|max)}' \
    < "$run/memory.csv" > "$run/memory-summary.json"
  hwm=$(awk '$1=="VmHWM:" {print $2}' "$run/process-status-after.txt")
  jq -s --argjson hwm "$hwm" '.[0]+.[1]+{process_hwm_since_restart_kib:$hwm}' \
    "$run/latency.json" "$run/memory-summary.json" > "$run/summary.json"
done
jq -s 'sort_by(.top_k,.concurrency,.phase)' "$output"/k*-c*/summary.json > "$output/summary.json"
touch "$output/COMPLETE"
