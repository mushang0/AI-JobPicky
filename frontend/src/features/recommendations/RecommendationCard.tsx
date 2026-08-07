import { useState } from "react";
import { BookmarkSimple, ChatCircleText, ThumbsDown, ThumbsUp, Trash, X } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import type { RecommendationCardView, RecommendationFeedback, RecommendationResultView } from "../../shared/api/types";
import { formatRecommendationDeadline } from "../../shared/formatting";
import { jobDetailPath, saveListScroll } from "../../shared/navigation";

type RecommendationItem = RecommendationCardView | RecommendationResultView;

export function RecommendationCard({ item, returnTo, onFeedback, onToggleSaved, onDelete }: { item: RecommendationItem; returnTo?: string; onFeedback: (feedback: RecommendationFeedback) => void; onToggleSaved: () => void; onDelete?: () => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const isDeleted = "is_deleted" in item && item.is_deleted;

  return (
    <article className={`recommendation-card ${isDeleted ? "recommendation-card-deleted" : ""}`}>
      <div className="recommendation-card-topline">
        <span className="match-score">AI 匹配度 {item.assessment.match_score}%</span>
        <span className={`recommendation-date recommendation-deadline${item.job.status === "CLOSED" ? " is-closed" : ""}`}>{formatRecommendationDeadline(item.job.deadline_at, item.job.status)}</span>
      </div>
      <Link className="recommendation-card-link" to={jobDetailPath(item.job.id, returnTo)} onClick={() => returnTo && saveListScroll(returnTo)}>
        <h2>{item.job.title}</h2>
        <p>{item.job.company_name}</p>
        <div className="recommendation-meta"><span>{item.job.locations.join("、") || "地点待确认"}</span>{item.job.company_nature && <span>{item.job.company_nature}</span>}</div>
      </Link>
      <div className="recommendation-reason"><ChatCircleText size={19} /><p>{item.assessment.reason}</p></div>
      <div className="recommendation-sections">
        {item.assessment.gaps.length > 0 && <RecommendationList title="能力缺口" values={item.assessment.gaps} icon={<X size={15} />} className="gap-list" />}
      </div>
      <div className="recommendation-card-footer">
        <div className="recommendation-actions" aria-label="推荐操作">
          <button className={`icon-button feedback-button ${item.feedback === "LIKE" ? "feedback-selected" : ""}`} type="button" aria-label="点赞" aria-pressed={item.feedback === "LIKE"} disabled={isDeleted} onClick={() => onFeedback(item.feedback === "LIKE" ? null : "LIKE")}><ThumbsUp size={17} /></button>
          <button className={`icon-button feedback-button ${item.feedback === "DISLIKE" ? "feedback-selected" : ""}`} type="button" aria-label="点踩" aria-pressed={item.feedback === "DISLIKE"} disabled={isDeleted} onClick={() => onFeedback(item.feedback === "DISLIKE" ? null : "DISLIKE")}><ThumbsDown size={17} /></button>
        <button className={`icon-button feedback-button ${item.is_saved ? "feedback-selected" : ""}`} type="button" aria-label={item.is_saved ? "取消收藏岗位" : "收藏岗位"} aria-pressed={item.is_saved} disabled={isDeleted} onClick={onToggleSaved}><BookmarkSimple size={19} weight={item.is_saved ? "fill" : "regular"} /></button>
        </div>
        {isDeleted ? <span className="deleted-label">已删除</span> : onDelete && (confirmDelete ? <span className="delete-confirm-actions"><button className="text-button" type="button" onClick={() => { onDelete(); setConfirmDelete(false); }}>确认删除</button><button className="text-button" type="button" onClick={() => setConfirmDelete(false)}>取消</button></span> : <button className="text-button danger-text" type="button" onClick={() => setConfirmDelete(true)}><Trash size={16} />删除推荐</button>)}
      </div>
    </article>
  );
}

function RecommendationList({ title, values, icon, className }: { title: string; values: string[]; icon: React.ReactNode; className: string }) {
  return <div className={`recommendation-list ${className}`}><strong>{title}</strong><ul>{values.map((value) => <li key={value}><span>{icon}</span>{value}</li>)}</ul></div>;
}
