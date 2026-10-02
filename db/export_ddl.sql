set serveroutput on size unlimited format wrapped
set feedback off heading off pagesize 0 linesize 32767 trimspool on
spool /tmp/xxwla_ddl.sql
declare
  c_owner constant varchar2(30) := 'MCP_VIEWS';
  type t_names is table of varchar2(128);
  l_tabs  t_names := t_names('XXWLA_CANDIDATE_SITE', 'XXWLA_GEO_POSTAL_CACHE');
  l_views t_names := t_names('XXWLA_DEMAND_V', 'XXWLA_GEO_PENDING_V', 'XXWLA_NETWORK_V');
  l_def  varchar2(32767);
  l_cond varchar2(32767);
  l_text varchar2(32767);
  l_cols varchar2(4000);
  l_first boolean;
  procedure p(s varchar2) is begin dbms_output.put_line(s); end;
begin
  p('-- MCP_VIEWS objects used by the warehouse agents.');
  p('-- Reconstructed from ALL_* dictionary views (the MCP user has no catalog role, so DBMS_METADATA is unavailable).');
  p('-- Storage clauses omitted. Grants for the MCP user are at the end of this file.');
  p('');
  for t in 1 .. l_tabs.count loop
    p('CREATE TABLE ' || c_owner || '.' || l_tabs(t) || ' (');
    l_first := true;
    for c in (select column_name, data_type, data_length, data_precision, data_scale,
                     char_length, char_used, nullable, data_default, column_id
                from all_tab_columns
               where owner = c_owner and table_name = l_tabs(t)
               order by column_id) loop
      l_def := c.data_default;
      p(case when l_first then '  ' else ', ' end || rpad(c.column_name, 32) ||
        case
          when c.data_type in ('VARCHAR2','CHAR','NVARCHAR2','NCHAR') then
            c.data_type || '(' || c.char_length || case c.char_used when 'C' then ' CHAR' else ' BYTE' end || ')'
          when c.data_type = 'NUMBER' and c.data_precision is not null then
            'NUMBER(' || c.data_precision || case when c.data_scale > 0 then ',' || c.data_scale end || ')'
          when c.data_type = 'NUMBER' and c.data_scale = 0 then 'INTEGER'
          when c.data_type = 'RAW' then 'RAW(' || c.data_length || ')'
          else c.data_type
        end ||
        case when l_def is not null then ' DEFAULT ' || trim(both chr(10) from trim(l_def)) end ||
        case when c.nullable = 'N' then ' NOT NULL' end);
      l_first := false;
    end loop;
    for k in (select constraint_name, constraint_type, search_condition, r_owner, r_constraint_name
                from all_constraints
               where owner = c_owner and table_name = l_tabs(t)
                 and constraint_type in ('P','U','C','R')
               order by decode(constraint_type,'P',1,'U',2,'R',3,4), constraint_name) loop
      l_cond := k.search_condition;
      continue when k.constraint_type = 'C' and l_cond like '%IS NOT NULL';
      select listagg(column_name, ', ') within group (order by position) into l_cols
        from all_cons_columns where owner = c_owner and constraint_name = k.constraint_name;
      l_text := null;
      if k.constraint_type = 'R' then
        select max(table_name) into l_text from all_constraints
         where owner = k.r_owner and constraint_name = k.r_constraint_name;
      end if;
      p(', CONSTRAINT ' || k.constraint_name || ' ' ||
        case k.constraint_type
          when 'P' then 'PRIMARY KEY (' || l_cols || ')'
          when 'U' then 'UNIQUE (' || l_cols || ')'
          when 'C' then 'CHECK (' || l_cond || ')'
          when 'R' then 'FOREIGN KEY (' || l_cols || ') REFERENCES ' || k.r_owner || '.' || l_text
        end);
    end loop;
    p(');');
    p('');
    for i in (select index_name, uniqueness from all_indexes
               where owner = c_owner and table_name = l_tabs(t)
                 and index_name not in (select index_name from all_constraints
                                         where owner = c_owner and table_name = l_tabs(t)
                                           and index_name is not null)
               order by index_name) loop
      select listagg(column_name, ', ') within group (order by column_position) into l_cols
        from all_ind_columns where index_owner = c_owner and index_name = i.index_name;
      p('CREATE ' || case when i.uniqueness = 'UNIQUE' then 'UNIQUE ' end || 'INDEX ' ||
        c_owner || '.' || i.index_name || ' ON ' || c_owner || '.' || l_tabs(t) || ' (' || l_cols || ');');
    end loop;
    p('');
  end loop;
  for v in 1 .. l_views.count loop
    select text into l_text from all_views where owner = c_owner and view_name = l_views(v);
    p('CREATE OR REPLACE VIEW ' || c_owner || '.' || l_views(v) || ' AS');
    p(rtrim(rtrim(l_text, chr(10) || ' '), ';') || ';');
    p('');
  end loop;
end;
/
spool off
exit
