;;; export-emacs-kb.el --- Export Emacs self-documentation as Prolog -*- lexical-binding: t; -*-

(require 'cl-lib)
(require 'subr-x)

(defun zara-emacs--prolog-quote (value)
  (let* ((text (if value (format "%s" value) ""))
         (text (replace-regexp-in-string "\\\\" "\\\\\\\\" text t t))
         (text (replace-regexp-in-string "'" "''" text t t))
         (text (replace-regexp-in-string "[[:cntrl:]]+" " " text t t)))
    (concat "'" text "'")))

(defun zara-emacs--safe-doc (symbol kind)
  (condition-case nil
      (pcase kind
        ('function (documentation symbol t))
        ('variable (documentation-property symbol 'variable-documentation t)))
    (error nil)))

(defun zara-emacs--symbol-file (symbol)
  (or (ignore-errors (symbol-file symbol 'defun))
      (ignore-errors (symbol-file symbol 'defvar))
      ""))

(defun zara-emacs--emit (stream predicate &rest args)
  (princ predicate stream)
  (princ "(" stream)
  (cl-loop for arg in args
           for first = t then nil
           do (unless first (princ "," stream))
           do (princ (zara-emacs--prolog-quote arg) stream))
  (princ ").\n" stream))

(defun zara-emacs-export-kb (path)
  (with-temp-file path
    (let ((stream (current-buffer)))
      (zara-emacs--emit stream "emacs_build_version" emacs-version)
      (zara-emacs--emit stream "emacs_build_system" system-configuration)
      (zara-emacs--emit stream "emacs_build_features"
                        (mapconcat #'symbol-name features " "))
      (mapatoms
       (lambda (symbol)
         (let ((name (symbol-name symbol))
               (file (zara-emacs--symbol-file symbol)))
           (when (fboundp symbol)
             (zara-emacs--emit stream "emacs_symbol_kind" name "function")
             (let ((doc (zara-emacs--safe-doc symbol 'function)))
               (when (and doc (not (string-empty-p doc)))
                 (zara-emacs--emit stream "emacs_doc" name "function" doc)))
             (when (commandp symbol)
               (zara-emacs--emit stream "emacs_symbol_kind" name "command")
               (dolist (key (ignore-errors (where-is-internal symbol nil nil)))
                 (zara-emacs--emit stream "emacs_keybinding"
                                   name
                                   (key-description key)))))
           (when (boundp symbol)
             (zara-emacs--emit stream "emacs_symbol_kind" name "variable")
             (let ((doc (zara-emacs--safe-doc symbol 'variable)))
               (when (and doc (not (string-empty-p doc)))
                 (zara-emacs--emit stream "emacs_doc" name "variable" doc))))
           (when (and file (not (string-empty-p file)))
             (zara-emacs--emit stream "emacs_symbol_source" name file)))))
      (zara-emacs--emit stream "emacs_kb_complete" "true"))))

(provide 'export-emacs-kb)
