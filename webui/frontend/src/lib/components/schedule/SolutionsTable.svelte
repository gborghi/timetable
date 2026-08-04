<!--
  Bottom panel of the Schedule page: list of saved solutions with
  activate / delete actions.
-->
<script>
  export let solutions = [];
  export let onActivate;     // (id) => void
  export let onDelete;       // (id) => void
</script>

<section class="card p-5">
  <h2 class="mb-3">Soluzioni salvate</h2>
  <div class="overflow-x-auto">
    <table class="tbl">
      <thead>
        <tr>
          <th>#</th><th>Nome</th><th>Tipo</th><th>Obj</th>
          <th>Metriche</th><th>Attiva?</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each solutions as s}
          <tr>
            <td>#{s.id}</td>
            <td>{s.name}</td>
            <td>{s.kind}</td>
            <td>{s.obj_value}</td>
            <td class="text-xs">
            <!--
              `feasible: false` is recorded by the solver and by any
              hand-edit made on an already-broken baseline. It used to
              be just another k=v in this blob, indistinguishable from
              the rest, on the row with the "attiva" button next to it.
            -->
            {#if s.metrics && s.metrics.feasible === false}
              <span class="text-red-700 font-semibold"
                    data-testid="solution-infeasible">non fattibile</span>
            {/if}
            {Object.entries(s.metrics || {}).map(([k, v]) => `${k}=${v}`).join(' ')}
          </td>
            <td>{s.is_active ? '✓' : ''}</td>
            <td>
              {#if !s.is_active}
                <button class="btn !text-xs !px-2 !py-1"
                        on:click={() => onActivate(s.id)}>attiva</button>
              {/if}
              <button class="btn-danger !text-xs !px-2 !py-1"
                      on:click={() => onDelete(s.id)}>x</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>
