-- 댓글-대댓글 연결을 위해 comment_no / parent_id 컬럼 추가
-- 실행: psql -U <user> -d <db> -f 0002_comment_parent.sql

ALTER TABLE mer_blog_comments
    ADD COLUMN IF NOT EXISTS comment_no VARCHAR(128),
    ADD COLUMN IF NOT EXISTS parent_id  VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_mer_blog_comments_comment_no
    ON mer_blog_comments (comment_no);

CREATE INDEX IF NOT EXISTS idx_mer_blog_comments_parent_id
    ON mer_blog_comments (parent_id);
