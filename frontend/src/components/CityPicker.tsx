import { useEffect, useMemo, useRef, useState } from "react";
import { CaretDown, CaretRight, Check, MagnifyingGlass, X } from "@phosphor-icons/react";
import { chinaCities } from "../shared/cities";

export function CityPicker({ values, onChange, label }: { values: string[]; onChange: (values: string[]) => void; label: string }) {
  const [open, setOpen] = useState(false);
  const [province, setProvince] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const matches = useMemo(() => chinaCities.flatMap((item) => item.cities.map((city) => ({ city, province: item.province }))).filter(({ city, province: itemProvince }) => city.includes(query.trim()) || itemProvince.includes(query.trim())), [query]);
  const summary = values.length === 0 ? "不限" : values.length <= 2 ? values.join("、") : `已选 ${values.length} 项`;

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  function toggle(city: string) {
    onChange(values.includes(city) ? values.filter((item) => item !== city) : [...values, city]);
  }

  function close() {
    setOpen(false);
    setProvince(null);
    setQuery("");
  }

  const group = chinaCities.find((item) => item.province === province);

  return <div className={`city-picker${open ? " is-open" : ""}`} ref={rootRef} role="group" aria-label={label}>
    <button type="button" className="city-picker-trigger" aria-label={label} aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((current) => !current)}><span className={values.length ? "" : "is-placeholder"}>{summary}</span><CaretDown size={16} /></button>
    {open && <div className="city-picker-menu" role="dialog" aria-label={`${label}选择`}>
      <div className="city-picker-menu-head"><strong>选择省份和城市</strong><button type="button" onClick={close} aria-label="关闭城市选择"><X size={16} /></button></div>
      <div className="city-picker-search"><MagnifyingGlass size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索城市" aria-label="搜索城市" />{query && <button type="button" onClick={() => setQuery("")} aria-label="清空搜索"><X size={14} /></button>}</div>
      {values.length > 0 && <div className="city-picker-selected"><span>已选</span>{values.map((city) => <span className="city-picker-selected-city" key={city}>{city}</span>)}</div>}
      {query ? <div className="city-picker-options city-picker-search-results">{matches.map(({ city, province: cityProvince }) => <button type="button" role="option" aria-selected={values.includes(city)} className={values.includes(city) ? "is-selected" : ""} key={`${cityProvince}-${city}`} onClick={() => toggle(city)}>{values.includes(city) && <Check size={14} />}{city}<small>{cityProvince}</small></button>)}{matches.length === 0 && <p className="city-picker-empty">没有找到匹配城市</p>}</div> : <div className="city-picker-cascade">
        <div className="city-picker-provinces">{chinaCities.map(({ province: itemProvince }) => <button type="button" className={province === itemProvince ? "is-active" : ""} key={itemProvince} onMouseEnter={() => setProvince(itemProvince)} onFocus={() => setProvince(itemProvince)} onClick={() => setProvince(itemProvince)}>{itemProvince}<CaretRight size={14} /></button>)}</div>
        <div className="city-picker-cities">{group ? <><strong>{group.province}</strong><div>{group.cities.map((city) => <button type="button" role="option" aria-selected={values.includes(city)} className={values.includes(city) ? "is-selected" : ""} key={city} onClick={() => toggle(city)}>{values.includes(city) && <Check size={14} />}{city}</button>)}</div></> : <span>将鼠标移到省份查看城市</span>}</div>
      </div>}
    </div>}
  </div>;
}
